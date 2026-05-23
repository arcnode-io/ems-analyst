"""Integration tests for MeasurementsService against a real Postgres.

The agent + HMI both consume measurements via server's REST endpoints
(principle: agent is just another client of server). Service serves
hourly-bucketed, gap-filled timeseries per (site, device, measurement)
— same shape the agent's old TimeseriesClient.query_hourly returned.

Schema:
  measurements(ts timestamptz, site_id text, device_id text,
               measurement text, unit text, value jsonb)
"""

import json
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from src.measurements.measurements_service import MeasurementsService


@pytest.fixture(scope="session")
def postgres_url() -> Generator[str]:
    """Session-scoped Postgres testcontainer — reused across tests."""
    with PostgresContainer(
        "postgres:15", username="postgres", password="testpw", dbname="postgres"
    ) as pg:
        port = int(pg.get_exposed_port(5432))
        yield f"postgres://postgres:testpw@localhost:{port}/postgres"


@pytest_asyncio.fixture
async def measurements_service(postgres_url: str) -> MeasurementsService:
    """Fresh MeasurementsService — schema created lazily on first call."""
    return MeasurementsService(postgres_url=postgres_url)


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
    unit: str,
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
            unit,
            json.dumps(value),
        )
    finally:
        await conn.close()


class TestMeasurementsService:
    """AAA — hourly-bucketed, gap-filled timeseries per (site, device, measurement)."""

    @pytest.mark.asyncio
    async def test_get_returns_bucketed_value_for_seeded_hour(
        self, postgres_url: str, measurements_service: MeasurementsService
    ) -> None:
        # Arrange — seed one point at the top of an hour, request a 2-hour window
        await _seed_measurements_table(postgres_url)
        bucket_ts = datetime.now(UTC).replace(minute=15, second=0, microsecond=0)
        await _insert_measurement(
            postgres_url,
            ts=bucket_ts,
            site_id="site-A",
            device_id="device-1",
            measurement="power_kw",
            unit="kw",
            value=42.5,
        )

        # Act — bucket=1h, agg=mean, window covers the seeded hour
        actual = await measurements_service.get(
            site_id="site-A",
            device_id="device-1",
            measurement="power_kw",
            start=bucket_ts.replace(minute=0),
            end=bucket_ts.replace(minute=0) + timedelta(hours=2),
            aggregation="mean",
        )

        # Assert — value bucketed under the hour, unit echoed
        assert actual.site_id == "site-A"
        assert actual.device_id == "device-1"
        assert actual.measurement == "power_kw"
        assert actual.unit == "kw"
        seeded_hour = bucket_ts.replace(minute=0)
        # at least one point matching the seeded hour with our value
        matching = [p for p in actual.points if p.ts == seeded_hour and p.value == 42.5]
        assert len(matching) == 1

    @pytest.mark.asyncio
    async def test_get_returns_none_value_for_missing_buckets(
        self, measurements_service: MeasurementsService
    ) -> None:
        # Arrange — window includes hours with no data → those buckets should
        # come back with value=None (gap-filled, not omitted).
        far_past = datetime(1999, 1, 1, tzinfo=UTC)

        # Act
        actual = await measurements_service.get(
            site_id="site-A",
            device_id="device-1",
            measurement="power_kw",
            start=far_past,
            end=far_past + timedelta(hours=3),
            aggregation="mean",
        )

        # Assert — every bucket present, every value None
        assert len(actual.points) >= 3
        assert all(p.value is None for p in actual.points)
