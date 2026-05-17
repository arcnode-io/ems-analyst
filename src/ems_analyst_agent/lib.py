"""Agent — pydantic-ai chat loop with MCP tools + semantic memory.

Per ADR-024 + portal self-serve rule, NO third-party LLM API keys —
Bedrock for cloud customers, Ollama for airgapped. Same provider drives
chat AND memory embeddings; one llm_provider per customer block.
"""

import asyncio
import os

from pydantic_ai import Agent as PydanticAgent, RunContext, Tool
from python_mcp_server.clients import make_embedder

from .config import chat_model, load_config
from .memory import MemoryService
from .prompts import load_system_prompt
from .tools.domain_mcp import create_mcp_server
from .tools.markets import get_market_data
from .tools.weather_api import get_weather_forecast


class AgentDeps:
    """Dependencies injected into agent tools."""

    def __init__(self, memory_service: MemoryService) -> None:
        """Initialize deps. memory_service is the only injected dependency.

        Backend URLs (graph + vector) are read from process env at the
        client layer — MemoryService takes VECTOR_URL at construction.
        """
        self.memory_service = memory_service


class Agent:
    """Agent that uses APIs, MCP servers, and memory to complete tasks."""

    def __init__(self) -> None:
        """Initialize the agent.

        VECTOR_URL is sourced from process env (compose env_file
        secrets.env). Chat model + embedder both come from cfg.yml's
        per-customer block.
        """
        config = load_config()
        embedder = make_embedder(config.settings)
        self.memory_service = MemoryService(
            postgres_url=os.environ["VECTOR_URL"],
            embedder=embedder,
        )

        # MCP server reads its graph + vector backends from the parent process env
        # (GRAPH_URL or NEPTUNE_HOST+AOSS_HOST, plus VECTOR_URL). Compose
        # populates these via env_file; tests set them before constructing Agent.
        mcp_server = create_mcp_server()

        # Create Pydantic AI agent with dependency injection.
        self.agent: PydanticAgent[AgentDeps] = PydanticAgent(
            chat_model(config.settings),
            deps_type=AgentDeps,
            # Tool() wrapper required for plain (non-RunContext) callables — pydantic-ai's
            # tools= type expects Tool[T] | (RunContext[T], ...) -> Any
            tools=[Tool(get_weather_forecast), Tool(get_market_data)],
            toolsets=[mcp_server],
            system_prompt=load_system_prompt(),
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
        """Async chat — safe to await from FastAPI handlers + async tests."""
        deps = AgentDeps(memory_service=self.memory_service)
        result = await self.agent.run(prompt, deps=deps)
        # Store the user prompt for semantic memory across conversations.
        embedding = await self.memory_service.generate_embedding(prompt)
        await self.memory_service.store_memory(f"User stated: {prompt}", embedding)
        return str(result.output)
