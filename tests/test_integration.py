import asyncio
import os
import time
from collections.abc import Generator
from urllib.parse import urlparse

import asyncpg
import pook
import pytest
from neo4j import AsyncGraphDatabase, AsyncDriver
from pgvector.asyncpg import register_vector

from src.ems_analyst_agent.config import load_config
from src.ems_analyst_agent.lib import Agent
from tests.fixtures.containers import start_neo4j, start_postgres


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
        # Wait for Neo4j
        max_retries = 30
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
                    embedding vector(1536),
                    timestamp TIMESTAMPTZ DEFAULT NOW()
                )
                """)
            # Seed initial memory
            dummy_embedding = [0.1] * 1536
            await conn.execute(
                "INSERT INTO conversation_memory (content, embedding) VALUES ($1, $2)",
                "User stated: My favorite color is blue",
                dummy_embedding,
            )
            await conn.close()

        asyncio.run(setup_pgvector())

        # python-mcp-server's GraphitiClient.from_env() expects creds embedded
        # in GRAPH_URL (Aura-style packaging). Pack them in here so the child
        # MCP process inherits a working backend handle.
        parsed = urlparse(neo4j.url)
        os.environ["GRAPH_URL"] = (
            f"{parsed.scheme}://neo4j:{neo4j_password}@{parsed.netloc}"
        )

        yield neo4j.url, postgres.url


class TestIntegration:
    """Integration tests for the application."""

    def test_mcp(self, test_containers: tuple[str, str]) -> None:
        """Test MCP domain server integration with real Neo4j."""
        neo4j_url, pg_url = test_containers
        os.environ["VECTOR_URL"] = pg_url
        os.environ["GRAPH_URL"] = neo4j_url
        agent = Agent()
        result = agent.chat(
            "what is the relationship b/w my company and department of defense?"
        )
        assert "company" in result.lower() or "contract" in result.lower()

    def test_api(self, test_containers: tuple[str, str]) -> None:
        """Test API tool integration using mocked HTTP responses."""
        cfg = load_config()

        if not cfg.e2e:
            pook.on()
            pook.enable_network()
            pook.get("https://api.openweathermap.org/data/2.5/weather").reply(200).json(
                {
                    "main": {"temp": 15.5},
                    "weather": [{"main": "Clouds", "description": "overcast clouds"}],
                }
            )

        neo4j_url, pg_url = test_containers
        os.environ["VECTOR_URL"] = pg_url
        os.environ["GRAPH_URL"] = neo4j_url
        agent = Agent()
        result = agent.chat("Whats the weather forecast for france tomorrow?")

        assert (
            "cloudy" in result.lower()
            or "weather" in result.lower()
            or "clouds" in result.lower()
        )

        if not cfg.e2e:
            pook.off()

    def test_memory(self, test_containers: tuple[str, str]) -> None:
        """Test agent semantic memory with real pgvector container."""
        neo4j_url, pg_url = test_containers
        os.environ["VECTOR_URL"] = pg_url
        os.environ["GRAPH_URL"] = neo4j_url
        agent = Agent()

        agent.chat("My favorite color is blue")
        agent.chat("When should I buy and sell energy stocks?")
        result = agent.chat("What is my favorite color?")

        assert "blue" in result.lower()
