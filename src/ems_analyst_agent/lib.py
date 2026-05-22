"""Agent — pydantic-ai chat loop with MCP tools + semantic memory.

Per ADR-024, no third-party LLM API keys: Bedrock for cloud customers,
Ollama for airgapped. One `llm_provider` per customer block drives both
chat and memory embeddings. Turn execution lives in `turn.py`; this
module is the Agent's construction + entrypoints.
"""

import asyncio
import logging
import os
from collections.abc import AsyncGenerator

from pydantic_ai import Agent as PydanticAgent, RunContext, Tool
from pydantic_ai.messages import ModelMessage
from python_mcp_server.clients import make_embedder

from .config import chat_model, load_config
from .device_api import DeviceApiClient
from .memory import MemoryService
from .prompts import load_system_prompt
from .schemas import AnalystMessage, TextContent
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
from .turn import AgentDeps, ChatTurnResult, run_turn_stream

log = logging.getLogger(__name__)

# Constructor-time guard — the analyst agent is read-only by design, so
# a tool whose name starts with a mutating verb must never register.
_FORBIDDEN_VERB_PREFIXES: tuple[str, ...] = (
    "set_",
    "dispatch_",
    "command_",
    "write_",
    "delete_",
    "create_",
    "update_",
)


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

        # ty cannot reconcile pydantic-ai's invariant Tool[T] / Toolset[T]
        # generics (the telemetry tools key on a structural deps subset,
        # the MCP toolset is deps-agnostic); both are safe at runtime.
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
        """Process a chat prompt and return prose (sync entry).

        For callers not already inside an event loop (CLI, sync scripts).
        Inside an async context use `chat_async` — run_sync + asyncio.run
        both blow up under a running loop.
        """
        return asyncio.run(self.chat_async(prompt))

    async def chat_async(self, prompt: str) -> str:
        """Async chat — prose only. For artifact-aware chat use chat_message."""
        msg = await self.chat_message(prompt)
        return _first_text(msg)

    async def chat_message(
        self,
        prompt: str,
        *,
        message_history: list[ModelMessage] | None = None,
    ) -> AnalystMessage:
        """Run a turn and return the full AnalystMessage (text + artifacts)."""
        return (await self.chat_turn(prompt, message_history=message_history)).message

    async def chat_turn(
        self,
        prompt: str,
        *,
        message_history: list[ModelMessage] | None = None,
    ) -> ChatTurnResult:
        """One agent turn — drains `chat_turn_stream` fully for its result.

        Drains to exhaustion rather than returning on the `result` event:
        that lets `run_turn_stream`'s `agent.iter()` context exit inside
        this task. Bailing early parks the generator mid-context, so it
        finalizes in another task → anyio "cancel scope exited in a
        different task".
        """
        result: ChatTurnResult | None = None
        async for name, payload in self.chat_turn_stream(
            prompt, message_history=message_history
        ):
            if name == "result":
                assert isinstance(payload, ChatTurnResult)
                result = payload
        if result is None:
            raise RuntimeError("chat_turn_stream ended without a result")
        return result

    def chat_turn_stream(
        self,
        prompt: str,
        *,
        message_history: list[ModelMessage] | None = None,
    ) -> AsyncGenerator[tuple[str, object]]:
        """Run a turn as a live event stream — see `turn.run_turn_stream`.

        Yields `tool_start` / `tool_end` events live, then a terminal
        `("result", ChatTurnResult)`. The SSE endpoint consumes this
        directly; `chat_turn` drains it.
        """
        deps = AgentDeps(
            memory_service=self.memory_service,
            server=self.server,
            device_api=self.device_api,
        )
        return run_turn_stream(self.agent, deps, prompt, message_history)


def _assert_read_only(tools: list[Tool[object]]) -> None:
    """Fail fast at Agent construction if a mutating-named tool sneaks in."""
    for tool in tools:
        # pydantic-ai Tool exposes the function via .function
        name = getattr(tool.function, "__name__", "")
        for prefix in _FORBIDDEN_VERB_PREFIXES:
            if name.startswith(prefix):
                raise ValueError(
                    f"Analyst agent is read-only; tool {name!r} starts with "
                    f"a mutating prefix ({prefix!r})."
                )


def _first_text(msg: AnalystMessage) -> str:
    """Concatenate the text content of a message — used by `chat()`."""
    return "\n".join(
        entry.text for entry in msg.content if isinstance(entry, TextContent)
    )
