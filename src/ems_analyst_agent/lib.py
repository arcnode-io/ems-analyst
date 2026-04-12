import asyncio
import os
from urllib.parse import urlparse

from pydantic_ai import Agent as PydanticAgent, RunContext

from .memory import MemoryService
from .tools.domain_mcp import create_mcp_server
from .tools.weather_api import get_weather_forecast


class AgentDeps:
    """Dependencies injected into agent tools."""

    def __init__(
        self, graph_db_url: str, vector_db_url: str, memory_service: MemoryService
    ) -> None:
        """Initialize dependencies with database URLs and memory service.

        Args:
            graph_db_url: Connection URL for the knowledge graph database
            vector_db_url: Connection URL for the vector/semantic memory database
            memory_service: Service for semantic memory operations

        """
        self.graph_db_url = graph_db_url
        self.vector_db_url = vector_db_url
        self.memory_service = memory_service


class Agent:
    """Agent that uses APIs, MCP servers, and memory to complete tasks."""

    def __init__(self, graph_db_url: str, vector_db_url: str) -> None:
        """Initialize the agent with database connections.

        Args:
            graph_db_url: Connection URL for the knowledge graph database
            vector_db_url: Connection URL for the vector/semantic memory database

        """
        self.graph_db_url = graph_db_url
        self.vector_db_url = vector_db_url

        # Create memory service for semantic conversation storage
        self.memory_service = MemoryService(vector_db_url)

        # Extract Neo4j password from URL or environment
        # Reason: MCP server needs password to connect to Neo4j
        parsed = urlparse(graph_db_url)
        neo4j_password: str = (
            parsed.password or os.getenv("NEO4J_PASSWORD", "") or "testpassword123"
        )

        # Create MCP server for knowledge graph access
        mcp_server = create_mcp_server(
            neo4j_url=graph_db_url,
            postgres_url=vector_db_url,
            neo4j_password=neo4j_password,
        )

        # Create Pydantic AI agent with dependency injection
        self.agent = PydanticAgent(
            "openai:gpt-4o-mini",
            deps_type=AgentDeps,
            tools=[get_weather_forecast],
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
        """Process a chat prompt and return a response.

        Args:
            prompt: The user's chat message

        Returns:
            The agent's response as a string

        """
        # Create dependencies for this chat session
        deps = AgentDeps(
            graph_db_url=self.graph_db_url,
            vector_db_url=self.vector_db_url,
            memory_service=self.memory_service,
        )

        # Run the agent synchronously
        result = self.agent.run_sync(prompt, deps=deps)

        # Store the user prompt in memory for future retrieval
        # Reason: This enables semantic memory across conversations
        async def store_memory() -> None:
            embedding = await self.memory_service.generate_embedding(prompt)
            await self.memory_service.store_memory(f"User stated: {prompt}", embedding)

        asyncio.run(store_memory())

        # Return the response output as a string
        return str(result.output)
