"""Unit tests for create_server — which tools a deployment advertises.

A deployment with no graph backend (graph.backend=none, e.g. the on-prem
demo) used to advertise search_knowledge / verify_fact / combined_search
anyway: each raised "no graph backend configured" in ~3 ms, and the model
wasted tool-call budget calling them (verify_fact is even "ALWAYS" step 1
in the guidance text). Advertise only what can work.
"""

import pytest
from mcp.server.fastmcp import FastMCP

from .config import Config, LogLevel, Neo4jGraph, NoneGraph, OllamaSettings
from .server import create_server

_GRAPH_TOOLS = {"search_knowledge", "verify_fact", "combined_search"}


def _config(graph: NoneGraph | Neo4jGraph) -> Config:
    return Config(
        log_level=LogLevel.DEBUG,
        e2e=False,
        settings=OllamaSettings(
            llm_provider="ollama",
            ollama_base_url="http://localhost:11434/v1",
            ollama_chat_model="qwen3.6:35b",
            ollama_embedding_model="qwen3-embedding:4b",
        ),
        graph=graph,
    )


async def _tool_names(server: FastMCP) -> set[str]:
    return {t.name for t in await server.list_tools()}


async def _guidance(server: FastMCP) -> str:
    """All guidance text a client can read: resources + the prompt."""
    parts: list[str] = []
    for resource in await server.list_resources():
        parts.extend(
            str(content.content) for content in await server.read_resource(resource.uri)
        )
    for prompt in await server.list_prompts():
        result = await server.get_prompt(prompt.name)
        parts.extend(str(m.content) for m in result.messages)
    return "\n".join(parts)


class TestCreateServerTools:
    """AAA — tools advertised follow the configured graph backend."""

    @pytest.mark.asyncio
    async def test_no_graph_backend_advertises_only_vector_search(self) -> None:
        """No graph backend -> only rag_search is registered."""
        # Arrange + Act
        server = create_server(_config(NoneGraph(backend="none")))

        # Assert
        assert await _tool_names(server) == {"rag_search"}

    @pytest.mark.asyncio
    async def test_graph_backend_advertises_graph_tools_too(self) -> None:
        """A configured graph backend keeps the graph tools."""
        # Arrange + Act
        server = create_server(_config(Neo4jGraph(backend="neo4j")))

        # Assert
        assert await _tool_names(server) == {"rag_search"} | _GRAPH_TOOLS


class TestGuidanceMatchesTools:
    """AAA — guidance text must never send the model to a tool that isn't there."""

    @pytest.mark.asyncio
    async def test_no_graph_backend_guidance_names_no_graph_tool(self) -> None:
        """No graph backend -> guidance points only at rag_search."""
        # Arrange + Act
        server = create_server(_config(NoneGraph(backend="none")))
        text = await _guidance(server)

        # Assert
        assert "rag_search" in text
        for tool in _GRAPH_TOOLS:
            assert tool not in text

    @pytest.mark.asyncio
    async def test_graph_backend_guidance_still_covers_graph_tools(self) -> None:
        """A configured graph backend keeps the full guidance."""
        # Arrange + Act
        server = create_server(_config(Neo4jGraph(backend="neo4j")))
        text = await _guidance(server)

        # Assert
        for tool in _GRAPH_TOOLS | {"rag_search"}:
            assert tool in text
