"""Agent — pydantic-ai chat loop with MCP tools + semantic memory.

Per ADR-024 + portal self-serve rule, NO third-party LLM API keys —
Bedrock for cloud customers, Ollama for airgapped. Same provider drives
chat AND memory embeddings; one llm_provider per customer block.
"""

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from pydantic_ai import Agent as PydanticAgent, RunContext, Tool, UsageLimits
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
)
from python_mcp_server.clients import make_embedder

from .config import chat_model, load_config
from .device_api import DeviceApiClient
from .memory import MemoryService
from .prompts import load_system_prompt
from .schemas import AnalystArtifact, AnalystMessage
from .server_client import ServerClient
from .tools.domain_mcp import create_mcp_server
from .tools.forecast import get_forecast
from .tools.geopolitical import get_energy_news
from .tools.markets import get_market_data
from .tools.telemetry_tools import (
    describe_site,
    query_energy_breakdown,
    query_markets,
    query_timeseries,
)
from .tools.topology_tool import get_topology
from .tools.weather_api import get_weather_forecast

log = logging.getLogger(__name__)

# Constructor-time guard so we never accidentally register a mutating
# tool on the analyst — frontend handoff Q2 (read-only by design).
_FORBIDDEN_VERB_PREFIXES: tuple[str, ...] = (
    "set_",
    "dispatch_",
    "command_",
    "write_",
    "delete_",
    "create_",
    "update_",
)

# Backstop against a tool-call loop — a normal turn is 3-5 calls;
# discipline guidance in the system prompt keeps it there. Hitting this
# raises UsageLimitExceeded → the turn returns its partial artifacts.
_TOOL_CALL_LIMIT: int = 10

# Human-readable action shown in the HMI live-trace per tool call —
# never raw args (frontend handoff #2). Unknown tools fall back below.
_TOOL_LABELS: dict[str, str] = {
    "describe_site": "Checking what data is queryable",
    "get_topology": "Reading site topology",
    "query_timeseries": "Querying the site historian",
    "get_forecast": "Pulling the published forecast",
    "query_markets": "Computing market revenue",
    "query_energy_breakdown": "Computing the energy mix",
    "get_weather_forecast": "Checking the weather",
    "get_market_data": "Querying ERCOT market data",
    "get_energy_news": "Scanning energy news",
}
_DEFAULT_TOOL_LABEL: str = "Searching the knowledge base"

# Tools whose result carries a one-line headline worth surfacing in the
# toolTrace `summary` (the HMI intel feed reads it). External-data tools
# only — internal tools have nothing headline-shaped to show.
_SUMMARY_TOOLS: frozenset[str] = frozenset(
    {"get_energy_news", "get_market_data", "get_weather_forecast"}
)


@dataclass
class ChatTurnResult:
    """One agent turn: HMI-facing AnalystMessage + raw pydantic-ai messages.

    `message` is what the HMI / `chat_message` consumer renders.
    `new_messages` is the lossless pydantic-ai trace (incl. tool calls +
    returns) that an upstream conversation store should persist so future
    turns can pre-load context. `status` is the turn outcome — `ok`,
    `capped` (tool-call budget hit), or `error`.
    """

    message: AnalystMessage
    new_messages: list[ModelMessage]
    status: str = "ok"


class AgentDeps:
    """Dependencies injected into agent tools."""

    def __init__(
        self,
        memory_service: MemoryService,
        server: ServerClient,
        device_api: DeviceApiClient,
    ) -> None:
        """Initialize deps.

        `artifacts` is mutated by telemetry tools; HTTP layer assembles
        the final AnalystMessage from prose + this list. `server` is
        the REST client over ems-analyst-server — agent reads telemetry
        + forecasts through it; single-site deploy so the server
        resolves its own site_id, no site in the URL. `device_api` is
        the client over ems-device-api — the DTM (device topology)
        source of truth.
        """
        self.memory_service = memory_service
        self.server = server
        self.device_api = device_api
        self.artifacts: list[AnalystArtifact] = []


class Agent:
    """Agent that uses APIs, MCP servers, and memory to complete tasks."""

    def __init__(self) -> None:
        """Initialize the agent.

        VECTOR_URL is sourced from process env (compose env_file
        secrets.env). Chat model + embedder come from cfg.defaults.yml
        with optional per-deploy overrides via cfg.customer.yml.
        """
        config = load_config()
        self.market = config.market
        embedder = make_embedder(config.settings)
        self.memory_service = MemoryService(
            postgres_url=os.environ["VECTOR_URL"],
            embedder=embedder,
        )
        self.server = ServerClient()
        self.device_api = DeviceApiClient()

        # MCP server reads its graph + vector backends from the parent process env
        # (GRAPH_URL or NEPTUNE_HOST+AOSS_HOST, plus VECTOR_URL). Compose
        # populates these via env_file; tests set them before constructing Agent.
        mcp_server = create_mcp_server()

        # Telemetry tools take RunContext[_ArtifactSink] (a structural
        # subset of AgentDeps). pydantic-ai's Tool generic is invariant
        # so ty flags this; safe at runtime since AgentDeps satisfies
        # _ArtifactSink (artifacts: list[AnalystArtifact]).
        tools = [
            Tool(get_weather_forecast),
            Tool(get_market_data),
            Tool(get_energy_news),
            Tool(get_topology),
            Tool(describe_site),
            Tool(query_timeseries),
            Tool(get_forecast),
            Tool(query_markets),
            Tool(query_energy_breakdown),
        ]
        _assert_read_only(tools)  # ty: ignore[invalid-argument-type]

        # Create Pydantic AI agent with dependency injection.
        # ty cannot reconcile pydantic-ai's invariant Tool[T] / Toolset[T]
        # generics (the MCP toolset is deps-agnostic); safe at runtime.
        self.agent: PydanticAgent[AgentDeps] = (
            PydanticAgent(  # ty: ignore[invalid-assignment]
                chat_model(config.settings),
                deps_type=AgentDeps,
                tools=tools,  # ty: ignore[invalid-argument-type]
                toolsets=[mcp_server],  # ty: ignore[invalid-argument-type]
                system_prompt=load_system_prompt(),
            )
        )

        # Scope LLM LMP / fuel-mix queries to the customer's hub.
        market = self.market

        @self.agent.system_prompt
        def inject_market_context() -> str:
            return (
                f"Wholesale market context: this deployment participates in "
                f"{market.wholesale_market.upper()} with settlement point "
                f"{market.settlement_point.value}. Scope LMP and market-data "
                f"queries to this hub unless the user explicitly asks otherwise."
            )

        # Register dynamic system prompt for memory injection
        @self.agent.system_prompt
        async def inject_memories(ctx: RunContext[AgentDeps]) -> str:
            """Retrieve and inject relevant memories into the system prompt.

            Best-effort — semantic recall is an enhancement, not core. A
            slow or unreachable embedder/vector store skips memory
            injection rather than failing the user's whole turn.
            """
            if not ctx.prompt:
                return ""
            try:
                query_embedding = await ctx.deps.memory_service.generate_embedding(
                    str(ctx.prompt)
                )
                memories = await ctx.deps.memory_service.search_memories(
                    query_embedding, limit=3
                )
            except Exception:
                log.warning(
                    "memory recall skipped — embedder/store down", exc_info=True
                )
                return ""
            if memories:
                return "Relevant memories from previous conversations:\n" + "\n".join(
                    f"- {memory}" for memory in memories
                )
            return ""

    def chat(self, prompt: str) -> str:
        """Process a chat prompt and return a response (sync entry).

        For callers that aren't already inside an event loop (CLI, sync
        scripts). Inside an async context (FastAPI handler, etc.) use
        chat_async — run_sync + asyncio.run both blow up under a
        running loop.
        """
        return asyncio.run(self.chat_async(prompt))

    async def chat_async(self, prompt: str) -> str:
        """Async chat — returns prose only. For artifact-aware chat use chat_message."""
        msg = await self.chat_message(prompt)
        return _first_text(msg)

    async def chat_message(
        self,
        prompt: str,
        *,
        message_history: list[ModelMessage] | None = None,
    ) -> AnalystMessage:
        """Run the agent and return a full AnalystMessage (text + artifacts).

        Thin wrapper around `chat_turn` for callers that don't need to
        persist the pydantic-ai message trace.
        """
        return (await self.chat_turn(prompt, message_history=message_history)).message

    async def chat_turn(
        self,
        prompt: str,
        *,
        message_history: list[ModelMessage] | None = None,
    ) -> ChatTurnResult:
        """One agent turn — HMI message + raw pydantic-ai trace.

        Non-streaming callers drain `chat_turn_stream` to its terminal
        result. The streaming SSE endpoint consumes the generator
        directly to emit live tool-trace events.
        """
        async for name, payload in self.chat_turn_stream(
            prompt, message_history=message_history
        ):
            if name == "result":
                assert isinstance(payload, ChatTurnResult)
                return payload
        raise RuntimeError("chat_turn_stream ended without a result")

    async def chat_turn_stream(
        self,
        prompt: str,
        *,
        message_history: list[ModelMessage] | None = None,
    ) -> AsyncIterator[tuple[str, object]]:
        """Run a turn, yielding live tool events then a terminal result.

        Yields, in order:
          ("tool_start", {seq, tool, label})            — per tool call
          ("tool_end",   {seq, tool, outcome, ms, summary})
          ("result", ChatTurnResult)                    — always last

        The SSE endpoint frames the tool_* events live and turns the
        result into the terminal `message` + `done` events; `chat_turn`
        just drains to the result. `seq` pairs a start with its end.
        """
        deps = AgentDeps(
            memory_service=self.memory_service,
            server=self.server,
            device_api=self.device_api,
        )
        pending: dict[str, tuple[int, str, float]] = {}
        trace: list[dict[str, object]] = []
        seq = 0
        try:
            async with self.agent.iter(
                prompt,
                deps=deps,
                message_history=message_history,
                usage_limits=UsageLimits(tool_calls_limit=_TOOL_CALL_LIMIT),
            ) as run:
                async for node in run:
                    if not PydanticAgent.is_call_tools_node(node):
                        continue
                    async with node.stream(run.ctx) as events:
                        async for event in events:
                            if isinstance(event, FunctionToolCallEvent):
                                seq += 1
                                tool = event.part.tool_name
                                pending[event.part.tool_call_id] = (
                                    seq,
                                    tool,
                                    time.perf_counter(),
                                )
                                yield (
                                    "tool_start",
                                    {
                                        "seq": seq,
                                        "tool": tool,
                                        "label": _TOOL_LABELS.get(
                                            tool, _DEFAULT_TOOL_LABEL
                                        ),
                                    },
                                )
                            elif isinstance(event, FunctionToolResultEvent):
                                started = pending.pop(event.part.tool_call_id, None)
                                if started is None:
                                    continue
                                eseq, tool, t0 = started
                                entry = _trace_entry(tool, event, eseq, t0)
                                trace.append(entry)
                                yield "tool_end", entry
                await self._store_prompt_memory(prompt)
                content: list[dict[str, object]] = [
                    {"type": "text", "text": str(run.result.output)},
                    *(
                        {
                            "type": "artifact",
                            "artifact": art.model_dump(by_alias=True),
                        }
                        for art in _presentable(deps.artifacts)
                    ),
                ]
                message = AnalystMessage.model_validate(
                    {
                        "role": "assistant",
                        "content": content,
                        "toolTrace": [_public_trace(t) for t in trace],
                    }
                )
                yield (
                    "result",
                    ChatTurnResult(
                        message=message,
                        new_messages=list(run.result.new_messages()),
                        status="ok",
                    ),
                )
        except UsageLimitExceeded:
            # Model looped past the budget — surface partial artifacts.
            log.warning("tool-call limit hit; returning partial artifacts")
            yield "result", _partial_turn(deps.artifacts, trace)

    async def _store_prompt_memory(self, prompt: str) -> None:
        """Persist the prompt for semantic recall — best-effort.

        A slow/unreachable embedder must not drop the answer the agent
        already produced.
        """
        try:
            embedding = await self.memory_service.generate_embedding(prompt)
            await self.memory_service.store_memory(f"User stated: {prompt}", embedding)
        except Exception:
            log.warning("memory store skipped — embedder/store down", exc_info=True)


def _presentable(artifacts: list[AnalystArtifact]) -> list[AnalystArtifact]:
    """Trim the raw tool-artifact list to what the user should actually see.

    Two passes: dedupe identical artifacts (a loopy turn repeats tool
    calls), then drop `table` artifacts when a chart is present —
    describe_site / get_topology tables are discovery scaffolding the
    agent uses to find names, not the answer once a chart was produced.
    """
    seen: set[tuple[str, str]] = set()
    deduped: list[AnalystArtifact] = []
    for art in artifacts:
        key = (art.kind, str(getattr(art.spec, "title", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(art)
    has_chart = any(a.kind in ("line", "bar", "pie") for a in deduped)
    if has_chart:
        return [a for a in deduped if a.kind != "table"]
    return deduped


def _result_summary(tool: str, event: FunctionToolResultEvent) -> str | None:
    """One-line headline from an external tool's result; None otherwise.

    Only the external-data tools carry something headline-shaped — the
    HMI intel feed surfaces it. First non-empty line, trimmed.
    """
    if tool not in _SUMMARY_TOOLS:
        return None
    text = str(getattr(event.part, "content", "")).strip()
    if not text:
        return None
    return text.splitlines()[0].strip()[:140] or None


def _trace_entry(
    tool: str, event: FunctionToolResultEvent, seq: int, t0: float
) -> dict[str, object]:
    """Build a trace row from a completed tool call (carries stream `seq`)."""
    outcome = "ok" if getattr(event.part, "part_kind", "") == "tool-return" else "error"
    return {
        "seq": seq,
        "tool": tool,
        "label": _TOOL_LABELS.get(tool, _DEFAULT_TOOL_LABEL),
        "outcome": outcome,
        "ms": int((time.perf_counter() - t0) * 1000),
        "summary": _result_summary(tool, event),
    }


def _public_trace(entry: dict[str, object]) -> dict[str, object]:
    """toolTrace row for the AnalystMessage — drops the stream-only `seq`."""
    return {k: v for k, v in entry.items() if k != "seq"}


def _partial_turn(
    artifacts: list[AnalystArtifact], trace: list[dict[str, object]]
) -> ChatTurnResult:
    """Assemble a turn from artifacts gathered before the tool-call cap.

    The model looped past its budget. Whatever charts it built are still
    useful — keep the presentable set, drop error artifacts, and surface
    the rest with a brief note instead of a bare failure.
    """
    kept = [a for a in _presentable(artifacts) if a.kind != "error"]
    note = (
        "I ran long working through that — here's the data I gathered. "
        "Ask a follow-up if you need more."
        if kept
        else "I couldn't finish that one — I ran out of tool budget before "
        "reaching an answer. Try a narrower question."
    )
    content: list[dict[str, object]] = [
        {"type": "text", "text": note},
        *(
            {"type": "artifact", "artifact": art.model_dump(by_alias=True)}
            for art in kept
        ),
    ]
    return ChatTurnResult(
        message=AnalystMessage.model_validate(
            {
                "role": "assistant",
                "content": content,
                "toolTrace": [_public_trace(t) for t in trace],
            }
        ),
        new_messages=[],
        status="capped",
    )


def _assert_read_only(tools: list[Tool[object]]) -> None:
    """Fail fast at Agent construction if a mutating-named tool sneaks in."""
    for tool in tools:
        # pydantic-ai Tool exposes the function via .function
        name = getattr(tool.function, "__name__", "")
        for prefix in _FORBIDDEN_VERB_PREFIXES:
            if name.startswith(prefix):
                raise ValueError(
                    f"Analyst agent is read-only; tool {name!r} starts with "
                    f"a mutating prefix ({prefix!r}). See HMI handoff Q2."
                )


def _first_text(msg: AnalystMessage) -> str:
    """Concatenate text content; used by the legacy str-returning chat()."""
    from .schemas import TextContent

    return "\n".join(
        entry.text for entry in msg.content if isinstance(entry, TextContent)
    )
