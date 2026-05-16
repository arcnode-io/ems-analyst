"""Boot-time DB seeding for vector + graph slices.

Mirrors ems-device-api/src/seed/seed_from_file.ts contract:
  - URL set + marker present  → skip
  - URL set + marker absent   → fetch + restore + write marker
  - URL unset                 → start empty (log + skip)
  - any fetch / restore error → fatal, propagate

Naming follows engine, not deployment — Neo4j cypher dump restores on
Aura cloud and ISO self-hosted alike via the bolt protocol.

Sources (public S3, no auth):
  vector        → vector.sql.gz             (plain pg_dump of knowledge)
  graph (Neo4j) → graph-neo4j.cypher.gz     (apoc.export.cypher.all output)
  graph (Neptune) → TODO when defense customer comes online; Bulk
                    Loader REST against s3://arcnode-public/seed/graph-neptune/

Markers:
  vector → arcnode_seed_markers row in postgres, slice='vector'
  graph  → :ArcnodeSeedMarker {slice:'graph'} node
"""

import asyncio
import gzip
import logging
import os
import urllib.request

import asyncpg
from neo4j import AsyncGraphDatabase, AsyncManagedTransaction

from .clients.graphiti_client import _split_neo4j_url

logger = logging.getLogger(__name__)

VECTOR_MARKER_SLICE = "vector"
GRAPH_MARKER_SLICE = "graph"


def _fetch_gunzip(url: str) -> str:
    """Fetch + gunzip a public S3 .gz artifact, return decoded text."""
    with urllib.request.urlopen(url) as resp:  # nosec B310  # noqa: S310
        return gzip.decompress(resp.read()).decode()


async def _psql_apply(dump_url: str, conn_url: str) -> None:
    """Stream the gzipped dump through `psql -f -` for restore.

    asyncpg.execute can't reliably run a multi-statement pg_dump:
    psql metacommands (\\restrict), COPY ... FROM stdin, dollar-quoted
    function bodies, and embedded newlines in INSERT VALUES all need
    a libpq client (psql), not asyncpg's simple query path. psql
    handles all of it natively.

    Requires `psql` binary in PATH — see consumer Dockerfile (must
    install postgresql-client alongside python).
    """
    with urllib.request.urlopen(dump_url) as resp:  # nosec B310  # noqa: S310
        sql = gzip.decompress(resp.read())
    proc = await asyncio.create_subprocess_exec(
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "--single-transaction",
        "-d",
        conn_url,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate(sql)
    if proc.returncode != 0:
        raise RuntimeError(
            f"psql restore failed (rc={proc.returncode}): "
            f"{stderr.decode(errors='replace')[-500:]}"
        )


async def seed_vector(seed_url: str) -> None:
    """Restore vector dump into VECTOR_URL postgres if marker absent.

    Restore via psql -f (subprocess) — see _psql_apply for why asyncpg
    can't run pg_dump output directly. Marker write goes through
    asyncpg afterwards so we can use a parameterized INSERT.

    Failure modes:
      - psql exits non-zero → RuntimeError; marker not written; safe to
        retry (psql will hit "already exists" on re-create unless the
        caller cleans up; recommended retry path = manually
        `DROP SCHEMA public CASCADE; CREATE SCHEMA public;`)
    """
    conn_url = os.environ["VECTOR_URL"]
    conn = await asyncpg.connect(conn_url)
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS arcnode_seed_markers ("
            "slice TEXT PRIMARY KEY, seeded_at TIMESTAMPTZ DEFAULT now())"
        )
        marker = await conn.fetchval(
            "SELECT 1 FROM arcnode_seed_markers WHERE slice=$1",
            VECTOR_MARKER_SLICE,
        )
        if marker:
            logger.info("vector slice already seeded; skipping")
            return
        logger.info("seeding vector slice from %s", seed_url)
        await _psql_apply(seed_url, conn_url)
        await conn.execute(
            "INSERT INTO arcnode_seed_markers (slice) VALUES ($1) "
            "ON CONFLICT DO NOTHING",
            VECTOR_MARKER_SLICE,
        )
        logger.info("vector slice seeded")
    finally:
        await conn.close()


async def seed_graph_neo4j(seed_url: str) -> None:
    """Restore cypher dump into GRAPH_URL Neo4j if marker absent.

    Restore + marker write run in one managed transaction via
    session.execute_write — partial failure rolls back so a retry
    starts from a clean state.
    """
    uri, user, password = _split_neo4j_url(os.environ["GRAPH_URL"])
    if user is None or password is None:
        raise RuntimeError("GRAPH_URL must include user:password (Aura format)")
    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    try:
        async with driver.session() as session:
            result = await session.run(
                "MATCH (m:ArcnodeSeedMarker {slice: $slice}) RETURN m LIMIT 1",
                slice=GRAPH_MARKER_SLICE,
            )
            if await result.single():
                logger.info("graph slice already seeded; skipping")
                return
        logger.info("seeding graph slice from %s", seed_url)
        cypher_script = _fetch_gunzip(seed_url)
        statements = [s.strip() for s in cypher_script.split(";\n") if s.strip()]

        async def _restore(tx: AsyncManagedTransaction) -> None:
            for stmt in statements:
                # Reason: stmt is from our own dump file — driver's
                # LiteralString constraint is for user-input safety,
                # doesn't apply to a controlled artifact.
                await tx.run(stmt)  # ty: ignore[invalid-argument-type]
            await tx.run(
                "MERGE (m:ArcnodeSeedMarker {slice: $slice}) "
                "ON CREATE SET m.seeded_at = datetime()",
                slice=GRAPH_MARKER_SLICE,
            )

        async with driver.session() as session:
            await session.execute_write(_restore)
        logger.info("graph slice seeded")
    finally:
        await driver.close()


async def seed_all(vector_url: str | None, graph_neo4j_url: str | None) -> None:
    """Run available seeds at boot. Skips a slice when its env conn is unset."""
    if vector_url and os.environ.get("VECTOR_URL"):
        await seed_vector(vector_url)
    else:
        logger.info("vector seed skipped (no VECTOR_URL or seed URL)")
    if graph_neo4j_url and os.environ.get("GRAPH_URL"):
        await seed_graph_neo4j(graph_neo4j_url)
    else:
        logger.info("graph neo4j seed skipped (no GRAPH_URL or seed URL)")
