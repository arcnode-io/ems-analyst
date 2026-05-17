"""Agent — pydantic-ai chat loop with MCP tools + semantic memory.

Per ADR-024 + portal self-serve rule, NO third-party LLM API keys —
Bedrock for cloud customers, Ollama for airgapped. Same provider drives
chat AND memory embeddings; one llm_provider per customer block.
"""

import asyncio
import os
from dataclasses import dataclass

from pydantic_ai import Agent as PydanticAgent, RunContext, Tool
from pydantic_ai.messages import ModelMessage
from python_mcp_server.clients import make_embedder

from .config import chat_model, load_config
from .memory import MemoryService
from .prompts import load_system_prompt
from .schemas import AnalystArtifact, AnalystMessage
from .timeseries import TimeseriesClient
from .tools.domain_mcp import create_mcp_server
from .tools.markets import get_market_data
from .tools.telemetry_tools import (
    describe_site,
    list_devices_where,
    query_energy_breakdown,
    query_markets,
    query_timeseries,
)
from .tools.weather_api import get_weather_forecast

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


@dataclass
class ChatTurnResult:
    """One agent turn: HMI-facing AnalystMessage + raw pydantic-ai messages.

    `message` is what the HMI / `chat_message` consumer renders.
    `new_messages` is the lossless pydantic-ai trace (incl. tool calls +
    returns) that an upstream conversation store should persist so future
    turns can pre-load context.
    """

    message: AnalystMessage
    new_messages: list[ModelMessage]


class AgentDeps:
    """Dependencies injected into agent tools."""

    def __init__(
        self,
        memory_service: MemoryService,
        site_id: str,
        timeseries: TimeseriesClient,
    ) -> None:
        """Initialize deps.

        `artifacts` is mutated by telemetry tools; HTTP layer assembles
        the final AnalystMessage from prose + this list. `site_id` is
        baked into the deployment via the SITE_ID env var. `timeseries`
        is the Postgres-protocol client over public.measurements.
        """
        self.memory_service = memory_service
        self.site_id = site_id
        self.timeseries = timeseries
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
        self.site_id = os.environ["SITE_ID"]
        self.timeseries = TimeseriesClient.from_env()

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
            Tool(describe_site),
            Tool(query_timeseries),
            Tool(query_markets),
            Tool(list_devices_where),
            Tool(query_energy_breakdown),
        ]
        _assert_read_only(tools)  # ty: ignore[invalid-argument-type]

        # Create Pydantic AI agent with dependency injection.
        # ty cannot reconcile the invariant Tool[T] generic; safe at runtime.
        self.agent: PydanticAgent[AgentDeps] = (
            PydanticAgent(  # ty: ignore[invalid-assignment]
                chat_model(config.settings),
                deps_type=AgentDeps,
                tools=tools,  # ty: ignore[invalid-argument-type]
                toolsets=[mcp_server],
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
            """Retrieve and inject relevant memories into system prompt."""
            if ctx.prompt:
                query_embedding = await ctx.deps.memory_service.generate_embedding(
                    str(ctx.prompt)
                )
                memories = await ctx.deps.memory_service.search_memories(
                    query_embedding, limit=3
                )

                if memories:
                    return (
                        "Relevant memories from previous conversations:\n"
                        + "\n".join(f"- {memory}" for memory in memories)
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
        """One agent turn — returns HMI message + raw pydantic-ai trace.

        The upstream server holds the multi-turn conversation. It pre-loads
        prior pydantic-ai ModelMessages via `message_history` so the LLM
        sees tool calls + returns from earlier turns; it persists
        `new_messages` after this call so the next turn can replay.
        """
        deps = AgentDeps(
            memory_service=self.memory_service,
            site_id=self.site_id,
            timeseries=self.timeseries,
        )
        result = await self.agent.run(
            prompt, deps=deps, message_history=message_history
        )
        # Store the user prompt for semantic memory across conversations.
        embedding = await self.memory_service.generate_embedding(prompt)
        await self.memory_service.store_memory(f"User stated: {prompt}", embedding)
        content: list[dict[str, object]] = [
            {"type": "text", "text": str(result.output)},
            *(
                {"type": "artifact", "artifact": art.model_dump(by_alias=True)}
                for art in deps.artifacts
            ),
        ]
        return ChatTurnResult(
            message=AnalystMessage.model_validate(
                {"role": "assistant", "content": content}
            ),
            new_messages=list(result.new_messages()),
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
