import asyncio
import os

from pydantic_ai import Agent as PydanticAgent, RunContext, Tool

from .memory import MemoryService
from .tools.domain_mcp import create_mcp_server
from .tools.weather_api import get_weather_forecast


class AgentDeps:
    """Dependencies injected into agent tools."""

    def __init__(self, memory_service: MemoryService) -> None:
        """Initialize dependencies with the memory service.

        Backend URLs (graph + vector) are no longer threaded through here.
        The MCP server reads GRAPH_URL or NEPTUNE_HOST + AOSS_HOST from
        the process env via GraphitiClient.from_env(). The MemoryService
        reads VECTOR_URL from env at Agent construction time.

        Args:
            memory_service: Service for semantic memory operations
        """
        self.memory_service = memory_service


class Agent:
    """Agent that uses APIs, MCP servers, and memory to complete tasks."""

    def __init__(self) -> None:
        """Initialize the agent.

        VECTOR_URL is sourced from process env (compose populates via
        env_file: secrets.env). Graph backend is read by the MCP server
        from the same env, no threading needed.
        """
        # Create memory service for semantic conversation storage
        self.memory_service = MemoryService(os.environ["VECTOR_URL"])

        # MCP server reads its graph + vector backends from the parent process env
        # (GRAPH_URL or NEPTUNE_HOST+AOSS_HOST, plus VECTOR_URL). Compose
        # populates these via env_file; tests set them before constructing Agent.
        mcp_server = create_mcp_server()

        # Create Pydantic AI agent with dependency injection.
        # Explicit type param tells ty that AgentDepsT == AgentDeps for run_sync(deps=...).
        self.agent: PydanticAgent[AgentDeps] = PydanticAgent(
            "openai:gpt-4o-mini",
            deps_type=AgentDeps,
            # Tool() wrapper required for plain (non-RunContext) callables — pydantic-ai's
            # tools= type expects Tool[T] | (RunContext[T], ...) -> Any
            tools=[Tool(get_weather_forecast)],
            toolsets=[mcp_server],
            system_prompt=(
                "You are a helpful assistant with access to knowledge graphs, "
                "APIs, and semantic memory. Use your tools to provide accurate, "
                "grounded responses."
            ),
        )

        # Register dynamic system prompt for memory injection
        @self.agent.system_prompt
        async def inject_memories(ctx: RunContext[AgentDeps]) -> str:
            """Retrieve and inject relevant memories into system prompt."""
            # Get the current user prompt from context
            # Reason: We need to search for memories relevant to the current query
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
        """Async chat — safe to await from FastAPI handlers + async tests."""
        deps = AgentDeps(memory_service=self.memory_service)
        result = await self.agent.run(prompt, deps=deps)
        # Store the user prompt for semantic memory across conversations.
        embedding = await self.memory_service.generate_embedding(prompt)
        await self.memory_service.store_memory(f"User stated: {prompt}", embedding)
        return str(result.output)
