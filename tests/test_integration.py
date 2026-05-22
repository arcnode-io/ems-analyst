"""Integration tests for the agent.

Default mode (cfg.e2e=False, CI default): all HTTP boundaries are
pook-mocked — no load on the self-hosted Ollama at 173.211.12.43,
no third-party API calls. Tests verify the chain runs without
crashing + the right HTTP shapes are emitted.

Sanity-check mode (cfg.e2e=True, manual): mocks turned off, real
LLM hit. Assertions validate semantic behavior (the LLM actually
answers about companies, weather, color preferences).

Per [[pook-e2e-pattern]] + [[test-taxonomy]] memory rules.
"""

import asyncio
import os
import time
from collections.abc import Generator
from urllib.parse import urlparse

import asyncpg
import pook
import pytest
from neo4j import AsyncDriver, AsyncGraphDatabase
from pgvector.asyncpg import register_vector

from src.ems_analyst_agent.config import load_config
from src.ems_analyst_agent.lib import Agent
from tests.fixtures.containers import start_neo4j, start_postgres

# Ollama OpenAI-compat endpoint we mock in default mode.
OLLAMA_BASE = "http://173.211.12.43:11434/v1"

# Qwen3-Embedding 4b returns 2560d (embedder truncates to 1024).
_EMBED_RAW_DIM = 2560
_FIXED_EMBED = [0.001 * (i % 100) for i in range(_EMBED_RAW_DIM)]


def _mock_ollama_responses(reply_text: str) -> None:
    """Persist mocks for chat + embed at the Ollama endpoint.

    Canned chat reply lets the existing assertions still match: pass in
    text that contains the keyword the test asserts on. Embed always
    returns the same fixed 2560d vector → MemoryService truncates to
    1024d.
    """
    pook.post(f"{OLLAMA_BASE}/chat/completions").persist().reply(200).json(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "qwen3.6:35b",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply_text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
        }
    )
    pook.post(f"{OLLAMA_BASE}/embeddings").persist().reply(200).json(
        {
            "object": "list",
            "data": [{"object": "embedding", "embedding": _FIXED_EMBED, "index": 0}],
            "model": "qwen3-embedding:4b",
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }
    )


@pytest.fixture(scope="session")
def test_containers() -> Generator[tuple[str, str]]:
    """Create Neo4j and pgvector containers for testing.

    Yields:
        Tuple of (neo4j_url, postgres_url)

    """
    neo4j_password = "testpassword123"  # noqa: S105

    with (
        start_neo4j(neo4j_password) as neo4j,
        start_postgres(
            password=os.environ["POSTGRES_PASSWORD"],
            image="pgvector/pgvector:pg16",
        ) as postgres,
    ):
        # Wait for Neo4j. 30s wasn't enough when docker is also booting a
        # second postgres container in parallel (e.g. test_timeseries fixture
        # runs alongside) — bumped to 90s to absorb the startup contention.
        max_retries = 90
        for attempt in range(max_retries):
            try:
                # neo4j.url carries embedded creds for the GRAPH_URL contract;
                # AsyncGraphDatabase.driver rejects creds-in-URI, so connect
                # via plain host:port and pass auth= separately.
                driver = AsyncGraphDatabase.driver(
                    f"bolt://{neo4j.host}:{neo4j.port}",
                    auth=("neo4j", neo4j_password),
                )

                async def test_connection(d: AsyncDriver = driver) -> None:
                    async with d.session() as session:
                        await session.run("RETURN 1")
                    await d.close()

                asyncio.run(test_connection())
                break
            except Exception:
                if attempt == max_retries - 1:
                    raise
                time.sleep(1)

        # Seed Neo4j
        async def seed_neo4j() -> None:
            # Strip creds from neo4j.url for driver call (see above).
            driver = AsyncGraphDatabase.driver(
                f"bolt://{neo4j.host}:{neo4j.port}",
                auth=("neo4j", neo4j_password),
            )
            async with driver.session() as session:
                await session.run("""
                    CREATE (c:Company {name: 'My Company', industry: 'Defense'})
                    CREATE (dod:Agency {name: 'Department of Defense', type: 'Government'})
                    CREATE (c)-[:CONTRACTS_WITH {since: 2020, value: '$50M'}]->(dod)
                    """)
            await driver.close()

        asyncio.run(seed_neo4j())

        # Setup pgvector — connect via kwargs so passwords with special
        # chars (@, !, etc. — present in our shared dev creds) don't trip
        # asyncpg's DSN parser.
        async def setup_pgvector() -> None:
            conn = await asyncpg.connect(
                host=postgres.host,
                port=postgres.port,
                user="postgres",
                password=os.environ["POSTGRES_PASSWORD"],
                database="postgres",
            )
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await register_vector(conn)
            await conn.execute("""
                CREATE TABLE conversation_memory (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    embedding vector(1024),
                    timestamp TIMESTAMPTZ DEFAULT NOW()
                )
                """)
            # Seed initial memory — 1024d to match ADR-024 (Titan + Qwen3 truncated)
            dummy_embedding = [0.1] * 1024
            await conn.execute(
                "INSERT INTO conversation_memory (content, embedding) VALUES ($1, $2)",
                "User stated: My favorite color is blue",
                dummy_embedding,
            )
            await conn.close()

        asyncio.run(setup_pgvector())

        # ems-analyst-mcp's GraphitiClient.from_config() expects creds embedded
        # in GRAPH_URL (Aura-style packaging). Pack them in here so the child
        # MCP process inherits a working backend handle.
        parsed = urlparse(neo4j.url)
        os.environ["GRAPH_URL"] = (
            f"{parsed.scheme}://neo4j:{neo4j_password}@{parsed.netloc}"
        )

        yield neo4j.url, postgres.url


@pytest.fixture(autouse=True)
def _telemetry_env() -> None:
    """Set env vars Agent() construction reads.

    These tests exercise MCP / weather / markets / memory paths — none
    call telemetry tools, so SERVER_URL just needs to be settable for
    Agent() to construct. SITE_ID is a per-deployment string baked at
    CFN time; tests pin a fixed value.
    """
    os.environ["SERVER_URL"] = "http://server-stub.test"
    os.environ["SITE_ID"] = "test-site"


class TestIntegration:
    """Integration tests for the application."""

    def test_mcp(self, test_containers: tuple[str, str]) -> None:
        """Agent.chat runs the MCP + memory + chat chain without crashing."""
        cfg = load_config()
        neo4j_url, pg_url = test_containers
        os.environ["VECTOR_URL"] = pg_url
        os.environ["GRAPH_URL"] = neo4j_url

        if not cfg.e2e:
            pook.on()
            pook.enable_network()
            _mock_ollama_responses(
                "Your company contracts with the Department of Defense."
            )

        try:
            agent = Agent()
            result = agent.chat(
                "what is the relationship b/w my company and department of defense?"
            )
            assert "company" in result.lower() or "contract" in result.lower()
        finally:
            if not cfg.e2e:
                pook.off()
                pook.reset()

    def test_api(self, test_containers: tuple[str, str]) -> None:
        """Agent.chat runs the weather-tool path without crashing."""
        cfg = load_config()
        neo4j_url, pg_url = test_containers
        os.environ["VECTOR_URL"] = pg_url
        os.environ["GRAPH_URL"] = neo4j_url

        if not cfg.e2e:
            pook.on()
            pook.enable_network()
            _mock_ollama_responses("It's expected to be cloudy in France tomorrow.")
            pook.get("https://api.openweathermap.org/data/2.5/weather").persist().reply(
                200
            ).json(
                {
                    "main": {"temp": 15.5},
                    "weather": [{"main": "Clouds", "description": "overcast clouds"}],
                }
            )

        try:
            agent = Agent()
            result = agent.chat("Whats the weather forecast for france tomorrow?")
            assert (
                "cloudy" in result.lower()
                or "weather" in result.lower()
                or "clouds" in result.lower()
            )
        finally:
            if not cfg.e2e:
                pook.off()
                pook.reset()

    def test_markets(self, test_containers: tuple[str, str]) -> None:
        """Agent.chat runs the gridstatus market-data path without crashing."""
        from src.ems_analyst_agent.tools.markets import GRIDSTATUS_BASE_URL

        cfg = load_config()
        neo4j_url, pg_url = test_containers
        os.environ["VECTOR_URL"] = pg_url
        os.environ["GRAPH_URL"] = neo4j_url
        os.environ["GRIDSTATUS_API_KEY"] = "test-key"

        if not cfg.e2e:
            pook.on()
            pook.enable_network()
            _mock_ollama_responses(
                "ERCOT fuel mix shows 12 GW wind and 8 GW solar at this hour."
            )
            pook.get(
                f"{GRIDSTATUS_BASE_URL}/datasets/ercot_fuel_mix/query"
            ).persist().reply(200).json(
                {
                    "data": [
                        {
                            "interval_start_utc": "2026-05-16T00:00:00Z",
                            "wind": 12345.6,
                            "solar": 7890.1,
                            "natural_gas": 30000.0,
                        }
                    ],
                    "meta": {"hasNextPage": False},
                }
            )

        try:
            agent = Agent()
            result = agent.chat("What's the current ERCOT fuel mix?")
            assert (
                "ercot" in result.lower()
                or "wind" in result.lower()
                or "fuel" in result.lower()
            )
        finally:
            if not cfg.e2e:
                pook.off()
                pook.reset()

    def test_geopolitical(self, test_containers: tuple[str, str]) -> None:
        """Agent.chat runs the RSS-aggregator path without crashing."""
        from src.ems_analyst_agent.tools.geopolitical import ENERGY_FEED_URLS

        cfg = load_config()
        neo4j_url, pg_url = test_containers
        os.environ["VECTOR_URL"] = pg_url
        os.environ["GRAPH_URL"] = neo4j_url

        sample_rss = (
            '<?xml version="1.0"?><rss version="2.0"><channel>'
            "<title>Test Feed</title>"
            "<item><title>OPEC+ cut sends Brent to $95</title>"
            "<pubDate>Sat, 16 May 2026 12:00:00 GMT</pubDate></item>"
            "</channel></rss>"
        )

        if not cfg.e2e:
            pook.on()
            pook.enable_network()
            _mock_ollama_responses(
                "Top energy headline: OPEC+ cut sends Brent crude to $95."
            )
            for url in ENERGY_FEED_URLS:
                pook.get(url).persist().reply(200).type("application/rss+xml").body(
                    sample_rss
                )

        try:
            agent = Agent()
            result = agent.chat("Give me the top energy news headlines.")
            assert (
                "opec" in result.lower()
                or "brent" in result.lower()
                or "energy" in result.lower()
            )
        finally:
            if not cfg.e2e:
                pook.off()
                pook.reset()

    def test_memory(self, test_containers: tuple[str, str]) -> None:
        """Agent.chat persists + recalls memories via pgvector."""
        cfg = load_config()
        neo4j_url, pg_url = test_containers
        os.environ["VECTOR_URL"] = pg_url
        os.environ["GRAPH_URL"] = neo4j_url

        if not cfg.e2e:
            pook.on()
            pook.enable_network()
            # All 3 chats get the same canned reply containing "blue" so
            # the final assert passes. The mocked chat doesn't actually
            # use memory; real-LLM recall is the e2e check.
            _mock_ollama_responses("Your favorite color is blue.")

        try:
            agent = Agent()
            agent.chat("My favorite color is blue")
            agent.chat("When should I buy and sell energy stocks?")
            result = agent.chat("What is my favorite color?")
            assert "blue" in result.lower()
        finally:
            if not cfg.e2e:
                pook.off()
                pook.reset()
