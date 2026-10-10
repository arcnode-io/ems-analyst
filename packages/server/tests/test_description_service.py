"""Integration tests for DescriptionService against a real Postgres.

Schema: measurements(ts timestamptz, site_id text, device_id text,
measurement text, unit text, value jsonb) — same table
MeasurementsService reads, see test_measurements_service.py.

describe() must return correct distinct (device, measurement) pairs
without a full-table scan: in a single-site deployment, filtering by
site_id alone has near-zero selectivity (nearly every row matches), so
a naive `GROUP BY device_id, measurement` or `SELECT DISTINCT` scans
the entire table regardless — confirmed live against the real
device_demo_site deployment (34s against ~58M rows, timing out the
agent's 15s HTTP budget). The index-skip-scan approach this service
uses instead touches O(distinct pairs) index entries, not O(rows).

No per-pair sample count: an earlier version added one via a
correlated COUNT(*) subquery, but that's O(rows in that series) per
pair and reintroduced the same O(table size) blowup this query exists
to avoid. Dropped since it was a display-only column, not load-bearing.
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
    """Session-scoped Postgres testcontainer — reused across tests."""
    with PostgresContainer(
        "postgres:15", username="postgres", password="testpw", dbname="postgres"
    ) as pg:
        port = int(pg.get_exposed_port(5432))
        yield f"postgres://postgres:testpw@localhost:{port}/postgres"


@pytest_asyncio.fixture
async def description_service(postgres_url: str) -> DescriptionService:
    """Fresh DescriptionService — schema created lazily on first call."""
    return DescriptionService(postgres_url=postgres_url)


async def _seed_measurements_table(postgres_url: str) -> None:
    """Create the canonical measurements table."""
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


async def _insert_measurement(
    postgres_url: str,
    ts: datetime,
    site_id: str,
    device_id: str,
    measurement: str,
    value: float,
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
            "kw",
            json.dumps(value),
        )
    finally:
        await conn.close()


class TestDescriptionService:
    """AAA — site inventory: distinct (device, measurement) pairs + counts."""

    @pytest.mark.asyncio
    async def test_describe_returns_distinct_pairs(
        self, postgres_url: str, description_service: DescriptionService
    ) -> None:
        # Arrange — 3 samples for one pair, 1 for another, different site ignored
        await _seed_measurements_table(postgres_url)
        now = datetime.now(UTC)
        for i in range(3):
            await _insert_measurement(
                postgres_url,
                ts=now + timedelta(minutes=i),
                site_id="site-K",
                device_id="bess_module_01",
                measurement="active_power",
                value=100.0,
            )
        await _insert_measurement(
            postgres_url,
            ts=now,
            site_id="site-K",
            device_id="cdu_01",
            measurement="status",
            value=1.0,
        )
        await _insert_measurement(
            postgres_url,
            ts=now,
            site_id="site-other",
            device_id="bess_module_01",
            measurement="active_power",
            value=100.0,
        )

        # Act
        actual = await description_service.describe("site-K")

        # Assert
        assert actual.site_id == "site-K"
        pairs = {(p.device_id, p.measurement) for p in actual.pairs}
        assert pairs == {
            ("bess_module_01", "active_power"),
            ("cdu_01", "status"),
        }

    @pytest.mark.asyncio
    async def test_describe_orders_by_device_then_measurement(
        self, postgres_url: str, description_service: DescriptionService
    ) -> None:
        # Arrange — insert out of order
        await _seed_measurements_table(postgres_url)
        now = datetime.now(UTC)
        for device, measurement in [
            ("gpu_node_2", "fan_speed"),
            ("gpu_node_1", "gpu_1_power"),
            ("gpu_node_1", "fan_speed"),
        ]:
            await _insert_measurement(
                postgres_url,
                ts=now,
                site_id="site-L",
                device_id=device,
                measurement=measurement,
                value=1.0,
            )

        # Act
        actual = await description_service.describe("site-L")

        # Assert — device_id then measurement, ascending
        order = [(p.device_id, p.measurement) for p in actual.pairs]
        assert order == [
            ("gpu_node_1", "fan_speed"),
            ("gpu_node_1", "gpu_1_power"),
            ("gpu_node_2", "fan_speed"),
        ]

    @pytest.mark.asyncio
    async def test_describe_empty_site_returns_no_pairs(
        self, postgres_url: str, description_service: DescriptionService
    ) -> None:
        # Arrange
        await _seed_measurements_table(postgres_url)

        # Act
        actual = await description_service.describe("no-such-site")

        # Assert
        assert actual.pairs == []
