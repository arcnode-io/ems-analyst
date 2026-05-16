"""Real-container integration tests for boot-time seed.

Two backends covered:
  - Neo4j (community container) — proves cypher restore + transactional
    rollback against any bolt-protocol Neo4j (Aura, ISO, dev container).
  - Postgres + pgvector — proves plain-SQL restore + transactional
    rollback against the vector slice destination.

Each test verifies the same contract: idempotent skip via marker, fatal
on partial failure with clean rollback so retry succeeds.
"""

import gzip
import io
import os
from collections.abc import AsyncIterator
from unittest.mock import patch
from urllib.parse import quote_plus

import asyncpg
import pytest
import pytest_asyncio
from neo4j import AsyncGraphDatabase
from testcontainers.neo4j import Neo4jContainer
from testcontainers.postgres import PostgresContainer

from src.python_mcp_server.clients.graphiti_client import _split_neo4j_url
from src.python_mcp_server.seed import (
    GRAPH_MARKER_SLICE,
    VECTOR_MARKER_SLICE,
    seed_graph_neo4j,
    seed_vector,
)

CYPHER_SCRIPT = """
CREATE (a:Foo {name: 'bar'});
CREATE (b:Foo {name: 'baz'});
""".strip()

PARTIAL_FAIL_CYPHER = """
CREATE (a:Foo {name: 'bar'});
THIS IS NOT VALID CYPHER;
CREATE (b:Foo {name: 'baz'});
""".strip()

VECTOR_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE knowledge (id SERIAL PRIMARY KEY, content TEXT, embedding vector(3));
INSERT INTO knowledge (content, embedding) VALUES ('hi', '[1,0,0]');
INSERT INTO knowledge (content, embedding) VALUES ('bye', '[0,1,0]');
""".strip()

PARTIAL_FAIL_VECTOR_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE knowledge (id SERIAL PRIMARY KEY, content TEXT, embedding vector(3));
INSERT INTO knowledge (content, embedding) VALUES ('hi', '[1,0,0]');
THIS IS NOT VALID SQL;
""".strip()


def _graph_url(container: Neo4jContainer) -> str:
    """Pack user:pass into the URL; matches Aura's env-var packaging."""
    host = container.get_container_host_ip()
    port = container.get_exposed_port(container.port)
    return f"bolt://{container.username}:{container.password}@{host}:{port}"


def _vector_url(container: PostgresContainer) -> str:
    """Build a postgres URL for VECTOR_URL env from a testcontainer.

    quote_plus the password — testcontainers generates passwords with
    URL-special chars that break asyncpg's URL parser otherwise.
    """
    return (
        f"postgresql://{container.username}:{quote_plus(container.password)}"
        f"@{container.get_container_host_ip()}"
        f":{int(container.get_exposed_port(5432))}/{container.dbname}"
    )


def _gzipped_response(body: str) -> io.BytesIO:
    """Mimic urllib.request.urlopen() return — a context-managed BytesIO."""
    return io.BytesIO(gzip.compress(body.encode()))


@pytest_asyncio.fixture(autouse=True)
async def _wipe_neo4j(neo4j: Neo4jContainer) -> AsyncIterator[None]:
    """Clear all nodes between tests — fixture is session-scoped, tests aren't."""
    yield
    clean_uri, user, password = _split_neo4j_url(_graph_url(neo4j))
    assert user is not None
    assert password is not None
    driver = AsyncGraphDatabase.driver(clean_uri, auth=(user, password))
    try:
        async with driver.session() as session:
            await session.run("MATCH (n) DETACH DELETE n")
    finally:
        await driver.close()


@pytest_asyncio.fixture(autouse=True)
async def _wipe_postgres(
    postgres_pgvector: PostgresContainer,
) -> AsyncIterator[None]:
    """Drop seed tables + marker between tests."""
    yield
    conn = await asyncpg.connect(_vector_url(postgres_pgvector))
    try:
        await conn.execute("DROP TABLE IF EXISTS knowledge CASCADE")
        await conn.execute("DROP TABLE IF EXISTS arcnode_seed_markers CASCADE")
    finally:
        await conn.close()


# ───────────────────────── Neo4j graph slice ─────────────────────────


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
    clean_uri, user, password = _split_neo4j_url(_graph_url(neo4j))
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


@pytest.mark.asyncio
async def test_seed_graph_neo4j_partial_failure_rolls_back_then_retries_clean(
    neo4j: Neo4jContainer,
) -> None:
    """Bad cypher mid-script → fail-fast, rollback, retry succeeds clean."""
    # Arrange
    os.environ["GRAPH_URL"] = _graph_url(neo4j)
    seed_url = "https://example.invalid/graph-neo4j.cypher.gz"
    clean_uri, user, password = _split_neo4j_url(_graph_url(neo4j))
    assert user is not None
    assert password is not None

    # Act — first call hits a script with a bad statement in the middle
    from neo4j.exceptions import CypherSyntaxError

    with (
        patch(
            "src.python_mcp_server.seed.urllib.request.urlopen",
            return_value=_gzipped_response(PARTIAL_FAIL_CYPHER),
        ),
        pytest.raises(CypherSyntaxError),
    ):
        await seed_graph_neo4j(seed_url)

    # Assert — DB is clean (transaction rolled back, no Foo nodes, no marker)
    driver = AsyncGraphDatabase.driver(clean_uri, auth=(user, password))
    try:
        async with driver.session() as session:
            result = await session.run("MATCH (n:Foo) RETURN count(n) AS c")
            row = await result.single()
            assert row is not None
            assert row["c"] == 0, "partial restore must roll back"

            marker = await session.run(
                "MATCH (m:ArcnodeSeedMarker {slice: $slice}) RETURN m",
                slice=GRAPH_MARKER_SLICE,
            )
            assert await marker.single() is None, "marker must not be set on failure"

        # Act — retry with a clean script (simulates upstream fix + redeploy)
        with patch(
            "src.python_mcp_server.seed.urllib.request.urlopen",
            return_value=_gzipped_response(CYPHER_SCRIPT),
        ):
            await seed_graph_neo4j(seed_url)

        # Assert — clean restore worked + marker now present
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
    finally:
        await driver.close()


# ──────────────────────── pgvector vector slice ──────────────────────


@pytest.mark.asyncio
async def test_seed_vector_loads_then_skips_on_rerun(
    postgres_pgvector: PostgresContainer,
) -> None:
    """First call seeds + marks; second call skips via marker."""
    # Arrange
    os.environ["VECTOR_URL"] = _vector_url(postgres_pgvector)
    seed_url = "https://example.invalid/vector.sql.gz"

    # Act — first call hits the SQL dump
    with patch(
        "src.python_mcp_server.seed.urllib.request.urlopen",
        return_value=_gzipped_response(VECTOR_SQL),
    ):
        await seed_vector(seed_url)

    # Assert — knowledge rows + marker landed
    conn = await asyncpg.connect(_vector_url(postgres_pgvector))
    try:
        rows = await conn.fetchval("SELECT count(*) FROM knowledge")
        assert rows == 2

        marker = await conn.fetchval(
            "SELECT 1 FROM arcnode_seed_markers WHERE slice=$1",
            VECTOR_MARKER_SLICE,
        )
        assert marker == 1
    finally:
        await conn.close()

    # Act — second call should NOT re-run the SQL (urlopen unused)
    with patch(
        "src.python_mcp_server.seed.urllib.request.urlopen",
        side_effect=AssertionError("urlopen must not be called on idempotent skip"),
    ):
        await seed_vector(seed_url)

    # Assert — still only 2 rows
    conn = await asyncpg.connect(_vector_url(postgres_pgvector))
    try:
        rows = await conn.fetchval("SELECT count(*) FROM knowledge")
        assert rows == 2
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_seed_vector_partial_failure_rolls_back_then_retries_clean(
    postgres_pgvector: PostgresContainer,
) -> None:
    """Bad SQL mid-script → fail-fast, rollback, retry succeeds clean."""
    # Arrange
    os.environ["VECTOR_URL"] = _vector_url(postgres_pgvector)
    seed_url = "https://example.invalid/vector.sql.gz"

    # Act — first call hits a SQL dump with a bad statement
    with (
        patch(
            "src.python_mcp_server.seed.urllib.request.urlopen",
            return_value=_gzipped_response(PARTIAL_FAIL_VECTOR_SQL),
        ),
        pytest.raises(asyncpg.PostgresSyntaxError),
    ):
        await seed_vector(seed_url)

    # Assert — knowledge table doesn't exist (rolled back); marker absent
    conn = await asyncpg.connect(_vector_url(postgres_pgvector))
    try:
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
            "WHERE table_name='knowledge')"
        )
        assert exists is False, "partial restore must roll back the table"

        marker = await conn.fetchval(
            "SELECT 1 FROM arcnode_seed_markers WHERE slice=$1",
            VECTOR_MARKER_SLICE,
        )
        assert marker is None, "marker must not be set on failure"
    finally:
        await conn.close()

    # Act — retry with a clean dump
    with patch(
        "src.python_mcp_server.seed.urllib.request.urlopen",
        return_value=_gzipped_response(VECTOR_SQL),
    ):
        await seed_vector(seed_url)

    # Assert — clean restore + marker present
    conn = await asyncpg.connect(_vector_url(postgres_pgvector))
    try:
        rows = await conn.fetchval("SELECT count(*) FROM knowledge")
        assert rows == 2

        marker = await conn.fetchval(
            "SELECT 1 FROM arcnode_seed_markers WHERE slice=$1",
            VECTOR_MARKER_SLICE,
        )
        assert marker == 1
    finally:
        await conn.close()
