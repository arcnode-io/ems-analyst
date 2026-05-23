"""Boot-time DB seeding for vector + graph slices.

Mirrors ems-device-api/src/seed/seed_from_file.ts contract:
  - URL set + marker present  → skip
  - URL set + marker absent   → fetch + restore + write marker
  - URL unset                 → start empty (log + skip)
  - any fetch / restore error → fatal, propagate

Naming follows engine, not deployment — Neo4j cypher dump restores on
Aura cloud and ISO self-hosted alike via the bolt protocol.

Sources (public S3, no auth):
  vector        → vector-cloud.sql.gz | vector-airgapped.sql.gz (pg_dump)
  graph (Neo4j) → graph-neo4j.cypher.gz     (apoc.export.cypher.all output)
  graph (Neptune) → s3://arcnode-public/seed/graph-neptune/{vertices,edges}.csv
                    loaded via Neptune Bulk Loader REST API (sigv4 IAM auth)

Markers:
  vector → arcnode_seed_markers row in postgres, slice='vector'
  graph  → :ArcnodeSeedMarker {slice:'graph'} node (Neo4j or Neptune)
"""

import asyncio
import csv
import gzip
import io
import json
import logging
import os
import time
import urllib.request
from collections.abc import Iterator
from typing import Final

import asyncpg
import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from neo4j import (
    AsyncDriver,
    AsyncGraphDatabase,
    AsyncManagedTransaction,
    AsyncSession,
)

from .clients.graphiti_client import _split_neo4j_url
from .config import Neo4jGraph, NeptuneGraph, NoneGraph

logger = logging.getLogger(__name__)

VECTOR_MARKER_SLICE = "vector"
GRAPH_MARKER_SLICE = "graph"

# Neptune Bulk Loader payload constants — see
# https://docs.aws.amazon.com/neptune/latest/userguide/bulk-load.html
# graph-neptune-v2/ has edges.csv stripped of multi-valued []-typed columns
# (Neptune doesn't allow multi-valued props on edges, even though Graphiti's
# default CSV export emits them). Vertices.csv is unchanged from the
# original — vertex multi-vals are fine. Original kept at graph-neptune/
# for Aura/self-hosted Neo4j paths that don't have this constraint.
NEPTUNE_S3_SOURCE = "s3://arcnode-public/seed/graph-neptune-v2/"
NEPTUNE_S3_HTTPS_BASE = (
    "https://arcnode-public.s3.us-east-1.amazonaws.com/seed/graph-neptune-v2/"
)

# graphiti's NeptuneDriver expects these AOSS indexes pre-populated to
# answer search queries. We populate them post-Neptune-load by streaming
# the same CSVs and projecting to the field subset graphiti indexes —
# see aoss_indices definition in graphiti_core.driver.neptune_driver.
_NODE_AOSS_FIELDS: tuple[str, ...] = ("uuid", "name", "summary", "group_id")
_EDGE_AOSS_FIELDS: tuple[str, ...] = ("uuid", "name", "fact", "group_id")
NEPTUNE_LOAD_POLL_INTERVAL_SEC = 10
NEPTUNE_LOAD_MAX_WAIT_SEC = 1800  # 30 min — bulk load of ~400MB is < 5 min typical
# Terminal load states; everything else is in-progress.
_NEPTUNE_LOAD_DONE_STATES = {
    "LOAD_COMPLETED",
    "LOAD_FAILED",
    "LOAD_CANCELLED_BY_USER",
    "LOAD_CANCELLED_DUE_TO_ERRORS",
}


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


# apoc.export.cypher.all emits schema DDL (CREATE/DROP CONSTRAINT|INDEX)
# interleaved with data writes. Neo4j forbids mixing the two in one
# transaction — schema statements run in their own auto-commit tx; data
# statements batch into managed write transactions.
_SCHEMA_STMT_PREFIXES: Final[tuple[str, ...]] = (
    "CREATE CONSTRAINT",
    "DROP CONSTRAINT",
    "CREATE INDEX",
    "DROP INDEX",
    "CREATE RANGE INDEX",
    "CREATE TEXT INDEX",
    "CREATE POINT INDEX",
    "CREATE FULLTEXT INDEX",
    "CREATE VECTOR INDEX",
)


def _is_schema_statement(stmt: str) -> bool:
    """True if `stmt` is a Neo4j schema (DDL) command."""
    head = stmt.lstrip().upper()
    return head.startswith(_SCHEMA_STMT_PREFIXES)


# apoc emits ~1900 data statements averaging ~245KB each — the full set
# in one transaction is ~465MB and exceeds Aura's tx-memory ceiling.
# 50/tx keeps each transaction ~12MB. Test fixtures are 2-3 statements,
# so they still flush as a single batch (rollback semantics preserved).
_DATA_BATCH_SIZE: Final[int] = 50


async def _wipe_graph(session: AsyncSession) -> None:
    """Drop every constraint, index, and node — clean slate before a load.

    The marker is written last; a marker-absent graph is therefore either
    empty or the debris of a failed run. apoc's schema DDL has no
    IF NOT EXISTS, so leftover constraints/indexes would collide on the
    retry. Wiping first makes the seed idempotent.
    """
    # Constraints before indexes — dropping a constraint drops its
    # backing index, so this avoids a double-drop error.
    for kind in ("CONSTRAINTS", "INDEXES"):
        result = await session.run(f"SHOW {kind} YIELD name RETURN name")
        names = [rec["name"] for rec in await result.data()]
        drop = "CONSTRAINT" if kind == "CONSTRAINTS" else "INDEX"
        for name in names:
            # name comes from SHOW output (our own graph), not user input;
            # backticked. ty flags the f-string as non-LiteralString.
            await session.run(
                f"DROP {drop} `{name}` IF EXISTS"  # ty: ignore[invalid-argument-type]
            )
    # Batched node delete — a big partial graph would blow tx memory.
    await session.run(
        "MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS"
    )


async def _graph_marker_present(driver: AsyncDriver) -> bool:
    """True if the graph seed marker node exists."""
    async with driver.session() as session:
        result = await session.run(
            "MATCH (m:ArcnodeSeedMarker {slice: $slice}) RETURN m LIMIT 1",
            slice=GRAPH_MARKER_SLICE,
        )
        return await result.single() is not None


async def seed_graph_neo4j(seed_url: str, e2e: bool = False) -> None:
    """Restore cypher dump into GRAPH_URL Neo4j.

    Production (e2e=False): skips when the marker node is present — a
    customer reboot must not re-seed. Marker absent → wipe + load + mark.

    e2e=True: ignores the marker, always wipes + re-seeds. An e2e run
    must exercise the seed workflow fresh every time; a leftover marker
    from a prior run would otherwise make it silently skip.

    Marker absent (or e2e) → the graph is wiped first (a failed prior run
    leaves schema debris apoc's no-IF-NOT-EXISTS DDL would collide with).

    Data statements commit in batches of _DATA_BATCH_SIZE managed write
    transactions — a failure within a batch rolls that batch back.
    Schema statements (constraints/indexes) run in their own auto-commit
    transactions; Neo4j rejects schema + write in one tx. Statement order
    is preserved: apoc emits CREATE CONSTRAINT before the bulk load,
    DROP after it.
    """
    uri, user, password = _split_neo4j_url(os.environ["GRAPH_URL"])
    if user is None or password is None:
        raise RuntimeError("GRAPH_URL must include user:password (Aura format)")
    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    try:
        if not e2e and await _graph_marker_present(driver):
            logger.info("graph slice already seeded; skipping")
            return
        logger.info("seeding graph slice from %s", seed_url)
        cypher_script = _fetch_gunzip(seed_url)
        statements = [s.strip() for s in cypher_script.split(";\n") if s.strip()]

        async with driver.session() as session:
            await _wipe_graph(session)
            data_batch: list[str] = []

            async def _flush_data() -> None:
                """Commit the accumulated data statements as one write tx."""
                if not data_batch:
                    return
                pending = list(data_batch)
                data_batch.clear()

                async def _write(tx: AsyncManagedTransaction) -> None:
                    for stmt in pending:
                        # Reason: stmt is from our own dump file — driver's
                        # LiteralString constraint guards user input, not a
                        # controlled artifact.
                        await tx.run(stmt)  # ty: ignore[invalid-argument-type]

                await session.execute_write(_write)

            for stmt in statements:
                if _is_schema_statement(stmt):
                    await _flush_data()
                    # Auto-commit: schema DDL can't share a tx with writes.
                    await session.run(stmt)  # ty: ignore[invalid-argument-type]
                else:
                    data_batch.append(stmt)
                    if len(data_batch) >= _DATA_BATCH_SIZE:
                        await _flush_data()
            await _flush_data()

            await session.run(
                "MERGE (m:ArcnodeSeedMarker {slice: $slice}) "
                "ON CREATE SET m.seeded_at = datetime()",
                slice=GRAPH_MARKER_SLICE,
            )
        logger.info("graph slice seeded")
    finally:
        await driver.close()


def _sigv4_headers(method: str, url: str, body: bytes = b"") -> dict[str, str]:
    """Sign a request with SigV4 against the neptune-db service.

    Returns the headers to attach to the actual httpx call. Uses the
    default boto3 credential chain → EC2 instance role in prod.
    """
    session = boto3.Session()
    creds = session.get_credentials()
    if creds is None:
        raise RuntimeError("no AWS credentials available for Neptune sigv4")
    # boto3's session already resolves region from AWS_REGION → ~/.aws/config
    # → EC2 IMDS; no need to read the env var ourselves.
    region = session.region_name or "us-east-1"
    req = AWSRequest(method=method, url=url, data=body)
    SigV4Auth(creds, "neptune-db", region).add_auth(req)
    return dict(req.headers)


async def _neptune_opencypher(host: str, query: str) -> dict:
    """POST an openCypher query to a Neptune cluster; return JSON results."""
    url = f"https://{host}:8182/opencypher"
    body = json.dumps({"query": query}).encode()
    headers = _sigv4_headers("POST", url, body)
    headers["Content-Type"] = "application/json"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, content=body, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _neptune_has_marker(host: str) -> bool:
    """Return True if the ArcnodeSeedMarker {slice:'graph'} node exists."""
    result = await _neptune_opencypher(
        host,
        "MATCH (m:ArcnodeSeedMarker) WHERE m.slice = 'graph' RETURN m LIMIT 1",
    )
    return bool(result.get("results"))


async def _neptune_write_marker(host: str) -> None:
    """Set the seed marker via openCypher MERGE."""
    await _neptune_opencypher(
        host,
        "MERGE (m:ArcnodeSeedMarker {slice: 'graph'}) "
        "ON CREATE SET m.seeded_at = datetime()",
    )


async def _neptune_start_load(host: str, loader_role_arn: str) -> str:
    """Kick off the Bulk Loader; return loadId."""
    url = f"https://{host}:8182/loader"
    region = boto3.Session().region_name or "us-east-1"
    body = json.dumps(
        {
            "source": NEPTUNE_S3_SOURCE,
            "format": "csv",
            "iamRoleArn": loader_role_arn,
            "region": region,
            # Tolerate per-row errors — the loader logs them via the
            # `errors` endpoint. The 1.5GB CSVs have a long-tail of
            # malformed rows that won't be fixed at the source; bailing
            # the whole load on a single parse error makes the seed
            # impossible. (Phase 8 v4 hit exactly this: 1 error in
            # 3.1M rows cancelled the entire load.)
            "failOnError": "FALSE",
            "parallelism": "MEDIUM",
            "updateSingleCardinalityProperties": "FALSE",
            "queueRequest": "TRUE",
        }
    ).encode()
    headers = _sigv4_headers("POST", url, body)
    headers["Content-Type"] = "application/json"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, content=body, headers=headers)
        resp.raise_for_status()
        payload = resp.json()["payload"]
        return payload["loadId"]


async def _neptune_wait_for_load(host: str, load_id: str) -> None:
    """Poll loader status until terminal; raise on failure."""
    url = f"https://{host}:8182/loader/{load_id}"
    deadline = time.monotonic() + NEPTUNE_LOAD_MAX_WAIT_SEC
    while True:
        headers = _sigv4_headers("GET", url)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            overall = resp.json()["payload"]["overallStatus"]
            status = overall["status"]
        if status == "LOAD_COMPLETED":
            logger.info("neptune load %s complete", load_id)
            return
        if status in _NEPTUNE_LOAD_DONE_STATES:
            raise RuntimeError(f"neptune load {load_id} ended with {status}: {overall}")
        if time.monotonic() > deadline:
            raise RuntimeError(
                f"neptune load {load_id} did not complete within "
                f"{NEPTUNE_LOAD_MAX_WAIT_SEC}s; last status: {status}"
            )
        logger.info("neptune load %s status=%s; polling", load_id, status)
        await asyncio.sleep(NEPTUNE_LOAD_POLL_INTERVAL_SEC)


def _stream_csv_projection(
    url: str, fields: tuple[str, ...]
) -> Iterator[dict[str, str]]:
    """Stream a public S3 CSV → yield dicts limited to the named fields.

    Streaming avoids materializing the full 113MB vertices.csv (most of
    which is the name_embedding column we don't need for AOSS).

    Neptune CSV headers are `name:Type` (e.g. `uuid:String`,
    `created_at:DateTime`). Strip the type suffix so callers can ask
    for bare `uuid` and get the matched column.
    """
    with urllib.request.urlopen(url) as resp:  # nosec B310  # noqa: S310
        text = io.TextIOWrapper(resp, encoding="utf-8")
        reader = csv.DictReader(text)
        if reader.fieldnames is None:
            return
        header_map = {h.split(":", 1)[0]: h for h in reader.fieldnames}
        for row in reader:
            out: dict[str, str] = {}
            for f in fields:
                src = header_map.get(f)
                if src and row.get(src):
                    out[f] = row[src]
            yield out


async def _populate_aoss_indexes(graph: NeptuneGraph) -> None:
    """Create AOSS indexes + bulk-load from the same CSVs Neptune loaded.

    graphiti's NeptuneDriver expects 4 AOSS indexes; for our use case
    (rag-search-style queries against the seed corpus) only the node and
    edge indexes carry queryable data — community + episode indexes are
    populated via runtime add_episode calls. Pre-creating empty indexes
    for those keeps graphiti's check happy without us writing dummy data.
    """
    from graphiti_core.driver.neptune_driver import NeptuneDriver

    aoss_host = graph.aoss_host.removeprefix("https://").removeprefix("http://")
    driver = NeptuneDriver(
        host=f"neptune-db://{graph.neptune_host}",
        aoss_host=aoss_host,
    )
    # Build all 4 indexes (create_index is idempotent at the API layer)
    await driver.build_indices_and_constraints(delete_existing=False)

    nodes = list(
        _stream_csv_projection(
            f"{NEPTUNE_S3_HTTPS_BASE}vertices.csv", _NODE_AOSS_FIELDS
        )
    )
    logger.info("populating AOSS node_name_and_summary (%d docs)", len(nodes))
    driver.save_to_aoss("node_name_and_summary", nodes)

    edges = list(
        _stream_csv_projection(f"{NEPTUNE_S3_HTTPS_BASE}edges.csv", _EDGE_AOSS_FIELDS)
    )
    logger.info("populating AOSS edge_name_and_fact (%d docs)", len(edges))
    driver.save_to_aoss("edge_name_and_fact", edges)


async def seed_graph_neptune(graph: NeptuneGraph) -> None:
    """Load pre-baked CSVs into Neptune via Bulk Loader if marker absent.

    Hosts + IAM role come from cfg.customer.yml (written by CFN UserData
    from CFN outputs). S3 source prefix is hardcoded — pre-baked artifacts
    at arcnode-public/seed/graph-neptune-v2/.

    Two-phase: (1) Neptune Bulk Loader for the graph itself, (2)
    opensearch bulk for graphiti's AOSS lucene indexes (without these
    graphiti.search 404s with index_not_found). Both phases drive off
    the same CSV data.

    Idempotent via :ArcnodeSeedMarker {slice:'graph'} node in Neptune.
    Re-running on a seeded cluster is a no-op (one openCypher check).
    """
    if await _neptune_has_marker(graph.neptune_host):
        logger.info("graph (neptune) slice already seeded; skipping")
        return
    logger.info(
        "seeding graph (neptune) slice from %s via role %s",
        NEPTUNE_S3_SOURCE,
        graph.loader_role_arn,
    )
    load_id = await _neptune_start_load(graph.neptune_host, graph.loader_role_arn)
    await _neptune_wait_for_load(graph.neptune_host, load_id)
    await _populate_aoss_indexes(graph)
    await _neptune_write_marker(graph.neptune_host)
    logger.info("graph (neptune) slice seeded")


def e2e_graph_seed_url(url: str | None, e2e: bool) -> str | None:
    """Swap the graph cypher dump for its small `-e2e` variant.

    cfg.e2e=true deployments seed graph from `graph-neo4j-e2e.cypher.gz`
    — 153 nodes, ~40s — so the customer seed path runs fast +
    deterministic in CI without the 96MB / one-mega-tx restore.
    Production (e2e=false) keeps the full artifact. Only graph has an
    e2e fixture today; the 25MB vector dump restores full either way.
    """
    if url is None or not e2e:
        return url
    return url.replace(".cypher.gz", "-e2e.cypher.gz")


async def seed_all(
    vector_url: str | None,
    graph_neo4j_url: str | None,
    graph: NoneGraph | Neo4jGraph | NeptuneGraph,
    e2e: bool = False,
) -> None:
    """Run available seeds at boot. Skips a slice when its conn is unset.

    Graph backend comes from cfg.graph:
      - Neo4jGraph + GRAPH_URL env + graph_neo4j_url → seed_graph_neo4j
      - NeptuneGraph (hosts + role from cfg) → seed_graph_neptune
      - NoneGraph → skip

    e2e=True forces the neo4j graph seed to re-run regardless of the
    marker — an e2e must exercise the seed fresh every time.
    """
    if vector_url and os.environ.get("VECTOR_URL"):
        await seed_vector(vector_url)
    else:
        logger.info("vector seed skipped (no VECTOR_URL or seed URL)")
    if isinstance(graph, Neo4jGraph):
        if graph_neo4j_url and os.environ.get("GRAPH_URL"):
            await seed_graph_neo4j(graph_neo4j_url, e2e=e2e)
        else:
            logger.info("graph seed skipped (no GRAPH_URL or seed URL)")
    elif isinstance(graph, NeptuneGraph):
        await seed_graph_neptune(graph)
    else:
        logger.info("graph seed skipped (cfg.graph.backend=none)")
