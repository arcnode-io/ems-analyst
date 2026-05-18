"""Integration tests for ForecastsService against a real Postgres.

The `forecasts` table is owned by ems-analyst-model's score+write step.
This service reads it for the agent + HMI via REST. Schema mirrors what
ems-analyst-model's score.py emits — keep in sync if either side moves.
"""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from src.forecasts.forecasts_service import ForecastsService


@pytest.fixture(scope="session")
def postgres_url() -> Generator[str]:
    """Session-scoped Postgres testcontainer — reused across tests."""
    with PostgresContainer(
        "postgres:15", username="postgres", password="testpw", dbname="postgres"
    ) as pg:
        port = int(pg.get_exposed_port(5432))
        yield f"postgres://postgres:testpw@localhost:{port}/postgres"


@pytest_asyncio.fixture
async def forecasts_service(postgres_url: str) -> ForecastsService:
    """Fresh ForecastsService — schema assumed upstream-owned."""
    return ForecastsService(postgres_url=postgres_url)


async def _seed_forecasts_table(postgres_url: str) -> None:
    """Create the forecasts table — same shape ems-analyst-model writes."""
    conn = await asyncpg.connect(postgres_url)
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS forecasts (
                forecast_for  TIMESTAMPTZ NOT NULL,
                site_id       TEXT NOT NULL,
                measurement   TEXT NOT NULL,
                unit          TEXT NOT NULL,
                value         DOUBLE PRECISION NOT NULL,
                model_name    TEXT NOT NULL,
                model_version INT NOT NULL,
                forecasted_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (forecast_for, site_id, measurement, model_name)
            )
        """)
    finally:
        await conn.close()


async def _insert_forecast(
    postgres_url: str,
    forecast_for: datetime,
    site_id: str,
    measurement: str,
    unit: str,
    value: float,
    model_name: str,
    model_version: int,
) -> None:
    conn = await asyncpg.connect(postgres_url)
    try:
        await conn.execute(
            "INSERT INTO forecasts "
            "(forecast_for, site_id, measurement, unit, value, "
            " model_name, model_version, forecasted_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
            "ON CONFLICT DO NOTHING",
            forecast_for,
            site_id,
            measurement,
            unit,
            value,
            model_name,
            model_version,
            datetime.now(UTC),
        )
    finally:
        await conn.close()


class TestForecastsService:
    """AAA — service reads forecast rows in a time window."""

    @pytest.mark.asyncio
    async def test_get_returns_seeded_forecast(
        self, postgres_url: str, forecasts_service: ForecastsService
    ) -> None:
        # Arrange
        await _seed_forecasts_table(postgres_url)
        fc_for = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=2)
        await _insert_forecast(
            postgres_url,
            forecast_for=fc_for,
            site_id="HB_NORTH",
            measurement="dam_lmp_price",
            unit="usd_per_mwh",
            value=42.5,
            model_name="dam-lmp-forecast",
            model_version=7,
        )

        # Act
        actual = await forecasts_service.get(
            site_id="HB_NORTH",
            measurement="dam_lmp_price",
            start=fc_for - timedelta(hours=1),
            end=fc_for + timedelta(hours=1),
        )

        # Assert
        assert actual.site_id == "HB_NORTH"
        assert actual.measurement == "dam_lmp_price"
        assert actual.unit == "usd_per_mwh"
        assert actual.model_name == "dam-lmp-forecast"
        assert actual.model_version == 7
        assert len(actual.points) == 1
        assert actual.points[0].forecast_for == fc_for
        assert actual.points[0].value == 42.5

    @pytest.mark.asyncio
    async def test_get_returns_empty_when_window_excludes_forecast(
        self, forecasts_service: ForecastsService
    ) -> None:
        # Arrange
        far_past = datetime(1999, 1, 1, tzinfo=UTC)

        # Act
        actual = await forecasts_service.get(
            site_id="HB_NORTH",
            measurement="dam_lmp_price",
            start=far_past,
            end=far_past + timedelta(hours=1),
        )

        # Assert
        assert actual.points == []
