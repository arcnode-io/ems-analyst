"""Integration tests for DescriptionService against a real Postgres.

Replaces TimeseriesClient.describe_site — distinct (device, measurement)
pairs at a site with sample counts. Lets the LLM discover what's actually
in the historian before guessing measurement names.
"""

import json
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from src.description.description_service import DescriptionService


@pytest.fixture(scope="session")
def postgres_url() -> Generator[str]:
    with PostgresContainer(
        "postgres:15", username="postgres", password="testpw", dbname="postgres"
    ) as pg:
        port = int(pg.get_exposed_port(5432))
        yield f"postgres://postgres:testpw@localhost:{port}/postgres"


@pytest_asyncio.fixture
async def description_service(postgres_url: str) -> DescriptionService:
    return DescriptionService(postgres_url=postgres_url)


async def _seed_measurements_table(postgres_url: str) -> None:
    conn = await asyncpg.connect(postgres_url)
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS measurements (
                ts          TIMESTAMPTZ,
                site_id     TEXT,
                device_id   TEXT,
                measurement TEXT,
                unit        TEXT,
                value       JSONB
            )
        """)
    finally:
        await conn.close()


async def _insert(
    postgres_url: str,
    ts: datetime,
    site_id: str,
    device_id: str,
    measurement: str,
    value: object,
) -> None:
    conn = await asyncpg.connect(postgres_url)
    try:
        await conn.execute(
            "INSERT INTO measurements "
            "(ts, site_id, device_id, measurement, unit, value) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            ts,
            site_id,
            device_id,
            measurement,
            "",
            json.dumps(value),
        )
    finally:
        await conn.close()


class TestDescriptionService:
    """AAA — distinct (device, measurement) pairs with sample counts."""

    @pytest.mark.asyncio
    async def test_lists_pairs_with_sample_counts(
        self, postgres_url: str, description_service: DescriptionService
    ) -> None:
        # Arrange — 2 devices, 3 measurements, varying sample counts
        await _seed_measurements_table(postgres_url)
        now = datetime.now(UTC).replace(microsecond=0)
        for i in range(3):
            await _insert(
                postgres_url, now - timedelta(hours=i), "site-E", "BESS-01", "soc", 50.0
            )
        await _insert(postgres_url, now, "site-E", "BESS-01", "power_kw", 12.0)
        await _insert(postgres_url, now, "site-E", "INV-02", "power_kw", 7.0)

        # Act
        actual = await description_service.describe(site_id="site-E")

        # Assert — three pairs, counts match
        by_pair = {(p.device_id, p.measurement): p.samples for p in actual.pairs}
        assert by_pair[("BESS-01", "soc")] == 3
        assert by_pair[("BESS-01", "power_kw")] == 1
        assert by_pair[("INV-02", "power_kw")] == 1

    @pytest.mark.asyncio
    async def test_returns_empty_pairs_for_unknown_site(
        self, description_service: DescriptionService
    ) -> None:
        # Act
        actual = await description_service.describe(site_id="site-nope")

        # Assert
        assert actual.pairs == []
