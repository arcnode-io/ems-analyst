"""Integration tests for MeasurementsService against a real Postgres.

The agent + HMI both consume measurements via server's REST endpoints
(principle: agent is just another client of server). This file proves
the service correctly reads the canonical `measurements` table shape
that platform-api's telemetry_writer produces.

Schema (matches the agent-side TimeseriesClient docstring):
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
    """Create the canonical measurements table + a deterministic test row."""
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
    measurement: str,
    unit: str,
    value: float,
    device_id: str = "device-1",
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
    """AAA — service reads canonical measurements rows in a time window."""

    @pytest.mark.asyncio
    async def test_get_returns_seeded_point(
        self, postgres_url: str, measurements_service: MeasurementsService
    ) -> None:
        # Arrange
        await _seed_measurements_table(postgres_url)
        ts = datetime.now(UTC).replace(microsecond=0)
        await _insert_measurement(
            postgres_url,
            ts=ts,
            site_id="site-A",
            measurement="power_kw",
            unit="kw",
            value=42.5,
        )

        # Act
        actual = await measurements_service.get(
            site_id="site-A",
            measurement="power_kw",
            start=ts - timedelta(hours=1),
            end=ts + timedelta(hours=1),
        )

        # Assert
        assert actual.site_id == "site-A"
        assert actual.measurement == "power_kw"
        assert actual.unit == "kw"
        assert len(actual.points) == 1
        assert actual.points[0].ts == ts
        assert actual.points[0].value == 42.5

    @pytest.mark.asyncio
    async def test_get_returns_empty_when_window_excludes_row(
        self,
        measurements_service: MeasurementsService,
    ) -> None:
        # Arrange — seeded row exists from prior test; query a window far in past
        far_past = datetime(1999, 1, 1, tzinfo=UTC)

        # Act
        actual = await measurements_service.get(
            site_id="site-A",
            measurement="power_kw",
            start=far_past,
            end=far_past + timedelta(hours=1),
        )

        # Assert
        assert actual.points == []
