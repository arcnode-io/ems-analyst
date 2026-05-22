"""Real-container integration test for GraphitiClient.from_config() Neo4j path.

Spins up a real Neo4j 5 community container and verifies that
from_config picks the Neo4j branch, splits creds out of GRAPH_URL,
actually connects via bolt, and that build_indices_and_constraints
fires real Cypher without exploding.

Ollama at arcnode dev endpoint (173.211.12.43:11434):
  - cfg.e2e=false (default, CI): pook intercepts /v1/embeddings, returns
    a 1024d zero vector — proves wiring without external dep.
  - cfg.e2e=true: hits real Ollama, free dogfood.
"""

import os

import pook
import pytest
from testcontainers.neo4j import Neo4jContainer

from src.ems_analyst_mcp.clients.graphiti_client import GraphitiClient
from src.ems_analyst_mcp.config import (
    Config,
    LogLevel,
    Neo4jGraph,
    OllamaSettings,
    load_config,
)
from tests.fixtures.containers import neo4j  # noqa: F401  pytest fixture

OLLAMA_BASE_URL = "http://173.211.12.43:11434/v1"
# Ollama Qwen3 returns 2560d; embedder truncates to EMBEDDING_DIM (1024).
OLLAMA_FULL_VEC = [0.0] * 2560


def _graph_url_with_embedded_creds(container: Neo4jContainer) -> str:
    """Aura-style: pack user:pass into the URL for env-var packaging."""
    host = container.get_container_host_ip()
    port = container.get_exposed_port(container.port)
    return f"bolt://{container.username}:{container.password}@{host}:{port}"


@pytest.mark.asyncio
async def test_from_config_connects_to_real_neo4j_and_search_returns_list(
    neo4j: Neo4jContainer,
) -> None:
    """from_config() with GRAPH_URL → real connect → search() returns a list.

    Pook (cfg.e2e=false) or real Ollama (cfg.e2e=true) handles the
    embedding call that fires when graphiti builds its lucene indexes
    + runs the hybrid search.
    """
    # Arrange
    cfg = load_config()
    os.environ["GRAPH_URL"] = _graph_url_with_embedded_creds(neo4j)

    if not cfg.e2e:
        pook.on()
        pook.enable_network()
        # build_indices_and_constraints + search both embed the query
        # text. Mock both as a single repeating matcher.
        pook.post(f"{OLLAMA_BASE_URL}/embeddings").persist().reply(200).json(
            {"data": [{"embedding": OLLAMA_FULL_VEC}]}
        )

    test_config = Config(
        log_level=LogLevel.INFO,
        e2e=cfg.e2e,
        settings=OllamaSettings(
            llm_provider="ollama",
            ollama_base_url=OLLAMA_BASE_URL,
            ollama_chat_model="qwen3.6:35b",
            ollama_embedding_model="qwen3-embedding:4b",
        ),
        graph=Neo4jGraph(backend="neo4j"),
    )

    try:
        client = GraphitiClient.from_config(test_config)

        # Smoke-test the connection: real Cypher against the container.
        await client.graphiti.build_indices_and_constraints()

        # Act
        results = await client.search("anything", limit=5)

        # Assert
        assert isinstance(
            results, list
        ), "search() should return a list even when the graph is empty"

        await client.close()
    finally:
        pook.off()
