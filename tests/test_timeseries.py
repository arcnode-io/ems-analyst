"""Integration tests for TimeseriesClient against real Postgres.

Pure SQL — no agent, no LLM. Verifies portable-SQL contract works
against vanilla Postgres (the lowest common denominator across Tiger /
Aurora+pg_partman / self-hosted Timescale deployments).
"""

import json
import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
import pytest_asyncio

from src.ems_analyst_agent.timeseries import TimeseriesClient
from tests.fixtures.containers import start_postgres

_SITE: str = "site-eval"


@pytest.fixture(scope="module")
def measurements_url() -> Generator[str]:
    """Postgres testcontainer pre-seeded with public.measurements rows."""
    with start_postgres(
        password=os.environ["POSTGRES_PASSWORD"],
        image="postgres:15",
    ) as pg:
        import asyncio

        async def seed() -> None:
            conn = await asyncpg.connect(pg.url)
            await conn.execute("""
                CREATE TABLE public.measurements (
                    ts          timestamptz NOT NULL,
                    site_id     text        NOT NULL,
                    device_id   text        NOT NULL,
                    measurement text        NOT NULL,
                    unit        text,
                    value       jsonb       NOT NULL
                );
                CREATE INDEX ON public.measurements
                    (site_id, device_id, measurement, ts DESC);
            """)
            now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
            # BESS-01 SoC, 6 hourly points, slope -2/hr.
            rows: list[tuple[datetime, str, str, str, str | None, str]] = [
                (
                    now - timedelta(hours=5 - hr),
                    _SITE,
                    "BESS-01",
                    "state_of_charge",
                    "%",
                    json.dumps(80.0 - hr * 2),
                )
                for hr in range(6)
            ]
            rows.extend(
                [
                    (now, _SITE, "BESS-01", "status", None, json.dumps("alarm")),
                    (now, _SITE, "BESS-02", "status", None, json.dumps("ok")),
                ]
            )
            await conn.executemany(
                "INSERT INTO public.measurements "
                "(ts, site_id, device_id, measurement, unit, value) "
                "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
                rows,
            )
            await conn.close()

        asyncio.run(seed())
        yield pg.url


@pytest_asyncio.fixture
async def client(measurements_url: str) -> TimeseriesClient:
    return TimeseriesClient(postgres_url=measurements_url)


class TestQueryHourly:
    @pytest.mark.asyncio
    async def test_returns_bucketed_rows(self, client: TimeseriesClient) -> None:
        # Arrange + Act
        rows = await client.query_hourly(
            site_id=_SITE,
            device_id="BESS-01",
            measurement="state_of_charge",
            window=timedelta(hours=8),
            aggregation="mean",
        )

        # Assert — buckets in the seed are populated; older buckets are None
        non_null = [y for _, y in rows if y is not None]
        assert len(non_null) >= 5
        assert max(non_null) == pytest.approx(80.0)
        assert min(non_null) == pytest.approx(70.0)

    @pytest.mark.asyncio
    async def test_max_aggregation(self, client: TimeseriesClient) -> None:
        rows = await client.query_hourly(
            site_id=_SITE,
            device_id="BESS-01",
            measurement="state_of_charge",
            window=timedelta(hours=8),
            aggregation="max",
        )
        non_null = [y for _, y in rows if y is not None]
        assert max(non_null) == pytest.approx(80.0)

    @pytest.mark.asyncio
    async def test_unknown_device_returns_empty(self, client: TimeseriesClient) -> None:
        rows = await client.query_hourly(
            site_id=_SITE,
            device_id="DOES-NOT-EXIST",
            measurement="state_of_charge",
            window=timedelta(hours=24),
            aggregation="mean",
        )
        # All buckets present but all None — no rows matched
        assert all(y is None for _, y in rows)


class TestListDevices:
    @pytest.mark.asyncio
    async def test_lists_distinct_with_status(self, client: TimeseriesClient) -> None:
        # Arrange + Act
        rows = await client.list_devices(site_id=_SITE)

        # Assert
        device_ids = {r["device"] for r in rows}
        assert device_ids == {"BESS-01", "BESS-02"}
        statuses = {r["device"]: r["status"] for r in rows}
        assert statuses["BESS-01"] == "alarm"
        assert statuses["BESS-02"] == "ok"

    @pytest.mark.asyncio
    async def test_filter_by_status(self, client: TimeseriesClient) -> None:
        rows = await client.list_devices(site_id=_SITE, status=["alarm"])
        assert {r["device"] for r in rows} == {"BESS-01"}
