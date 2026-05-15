"""Real-container integration test for seed.seed_graph_neo4j.

Spins up a Neo4j 5 community container, stubs the public S3 fetch with
a tiny gzipped cypher script, and verifies:
  - first call restores the cypher + writes the marker
  - second call short-circuits via the marker (idempotent)

Bolt protocol + cypher format are identical across Aura, ISO self-hosted,
and the community container — so a single integration target proves the
restore path works wherever the customer's Neo4j lives.
"""

import gzip
import io
import os
from unittest.mock import patch

import pytest
from neo4j import AsyncGraphDatabase
from testcontainers.neo4j import Neo4jContainer

from src.python_mcp_server.seed import GRAPH_MARKER_SLICE, seed_graph_neo4j

CYPHER_SCRIPT = """
CREATE (a:Foo {name: 'bar'});
CREATE (b:Foo {name: 'baz'});
""".strip()


def _graph_url(container: Neo4jContainer) -> str:
    """Pack user:pass into the URL; matches Aura's env-var packaging."""
    host = container.get_container_host_ip()
    port = container.get_exposed_port(container.port)
    return f"bolt://{container.username}:{container.password}@{host}:{port}"


def _gzipped_response(body: str) -> io.BytesIO:
    """Mimic urllib.request.urlopen() return — a context-managed BytesIO."""
    return io.BytesIO(gzip.compress(body.encode()))


@pytest.mark.asyncio
async def test_seed_graph_neo4j_loads_then_skips_on_rerun(
    neo4j: Neo4jContainer,
) -> None:
    """First call seeds + marks; second call skips via marker."""
    # Arrange
    os.environ["GRAPH_URL"] = _graph_url(neo4j)
    seed_url = "https://example.invalid/graph-neo4j.cypher.gz"

    # Act — first call hits the cypher script
    with patch(
        "src.python_mcp_server.seed.urllib.request.urlopen",
        return_value=_gzipped_response(CYPHER_SCRIPT),
    ):
        await seed_graph_neo4j(seed_url)

    # Assert — both Foo nodes landed
    uri = _graph_url(neo4j)
    from src.python_mcp_server.clients.graphiti_client import _split_neo4j_url

    clean_uri, user, password = _split_neo4j_url(uri)
    assert user is not None
    assert password is not None
    driver = AsyncGraphDatabase.driver(clean_uri, auth=(user, password))
    try:
        async with driver.session() as session:
            result = await session.run("MATCH (n:Foo) RETURN count(n) AS c")
            row = await result.single()
            assert row is not None
            assert row["c"] == 2

            marker = await session.run(
                "MATCH (m:ArcnodeSeedMarker {slice: $slice}) RETURN m",
                slice=GRAPH_MARKER_SLICE,
            )
            assert await marker.single() is not None

        # Act — second call should NOT re-run the cypher (urlopen unused)
        with patch(
            "src.python_mcp_server.seed.urllib.request.urlopen",
            side_effect=AssertionError("urlopen must not be called on idempotent skip"),
        ):
            await seed_graph_neo4j(seed_url)

        # Assert — still only 2 Foo nodes (no duplicates from a second restore)
        async with driver.session() as session:
            result = await session.run("MATCH (n:Foo) RETURN count(n) AS c")
            row = await result.single()
            assert row is not None
            assert row["c"] == 2
    finally:
        await driver.close()
