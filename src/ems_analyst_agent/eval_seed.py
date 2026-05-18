"""Postgres testcontainer + measurements seed for the eval harnesses.

Both eval.py and eval_mcp.py need a `ServerClient` so the agent's
telemetry tools work; for the eval we don't actually want to spin up a
FastAPI server, so `EvalServerClient` reads the seeded Postgres
directly with the same SQL ems-analyst-server's services use.

Per [[project-eval-limitations]] this is LLM-in-isolation — the eval
measures the model's tool-calling choices, not the HTTP transport.
Full-stack-through-server lives in tests/test_integration.py.
"""

import json
import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import asyncpg

from .server_client import (
    Aggregation,
    DeviceList,
    DeviceRow,
    ForecastSeries,
    MeasurementPair,
    MeasurementPoint,
    MeasurementSeries,
    ServerClient,
    SiteDescription,
)

log = logging.getLogger(__name__)

EVAL_SITE_ID: Final[str] = "eval-site"
_DEVICES: Final[tuple[str, ...]] = ("BESS-01", "BESS-02", "BESS-03")

# Make the testcontainer fixtures from the integration test layer
# importable. The eval is dev-only (poe eval-live / eval-mcp) so
# pulling from tests/ is fine — it never ships in a release artifact.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from tests.fixtures.containers import start_postgres  # noqa: E402

_AGG_SQL: dict[Aggregation, str] = {
    "mean": "AVG((value::text)::float)",
    "max": "MAX((value::text)::float)",
    "min": "MIN((value::text)::float)",
    "last": "(ARRAY_AGG((value::text)::float ORDER BY ts DESC))[1]",
}


class EvalServerClient(ServerClient):
    """ServerClient impl that reads Postgres directly — bypasses HTTP for eval."""

    def __init__(self, postgres_url: str) -> None:
        """Take a Postgres URL; parent's base_url is unused but typed."""
        self._postgres_url = postgres_url
        self.base_url = "http://eval-fake"  # parent expects this attribute

    async def get_measurements(
        self,
        site_id: str,
        device_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
        aggregation: Aggregation = "mean",
    ) -> MeasurementSeries:
        """Hourly-bucketed gap-filled — mirrors MeasurementsService SQL."""
        agg_sql = _AGG_SQL[aggregation]
        sql = f"""
            WITH buckets AS (
                SELECT generate_series(
                    date_trunc('hour', $1::timestamptz),
                    date_trunc('hour', $2::timestamptz),
                    interval '1 hour'
                ) AS ts
            ),
            agg AS (
                SELECT date_trunc('hour', ts) AS bucket,
                       {agg_sql} AS y,
                       (ARRAY_AGG(unit ORDER BY ts DESC))[1] AS unit
                FROM measurements
                WHERE site_id = $3 AND device_id = $4 AND measurement = $5
                  AND ts >= $1::timestamptz AND ts <  $2::timestamptz
                GROUP BY bucket
            )
            SELECT b.ts, a.y, a.unit
            FROM buckets b LEFT JOIN agg a ON a.bucket = b.ts
            ORDER BY b.ts
        """  # noqa: S608  # nosec B608
        conn = await asyncpg.connect(self._postgres_url)
        try:
            rows = await conn.fetch(sql, start, end, site_id, device_id, measurement)
        finally:
            await conn.close()
        unit = next((str(r["unit"]) for r in rows if r["unit"] is not None), "")
        points = [
            MeasurementPoint(
                ts=r["ts"], value=None if r["y"] is None else float(r["y"])
            )
            for r in rows
        ]
        return MeasurementSeries(
            site_id=site_id,
            device_id=device_id,
            measurement=measurement,
            unit=unit,
            points=points,
        )

    async def list_devices(
        self, site_id: str, status: list[str] | None = None
    ) -> DeviceList:
        """Distinct devices + latest status — mirrors DevicesService SQL."""
        sql = """
            WITH latest_status AS (
                SELECT DISTINCT ON (device_id)
                       device_id, (value::text) AS status
                FROM measurements
                WHERE site_id = $1 AND measurement = 'status'
                ORDER BY device_id, ts DESC
            )
            SELECT DISTINCT m.device_id, ls.status
            FROM measurements m
            LEFT JOIN latest_status ls ON ls.device_id = m.device_id
            WHERE m.site_id = $1
            ORDER BY m.device_id
        """
        conn = await asyncpg.connect(self._postgres_url)
        try:
            rows = await conn.fetch(sql, site_id)
        finally:
            await conn.close()

        def _strip(s: str | None) -> str | None:
            if s is None:
                return None
            v = str(s)
            return v[1:-1] if v.startswith('"') and v.endswith('"') else v

        devices = [
            DeviceRow(device_id=str(r["device_id"]), status=_strip(r["status"]))
            for r in rows
        ]
        if status:
            devices = [d for d in devices if d.status in status]
        return DeviceList(site_id=site_id, devices=devices)

    async def describe_site(self, site_id: str) -> SiteDescription:
        """(device, measurement, samples) inventory — mirrors DescriptionService."""
        conn = await asyncpg.connect(self._postgres_url)
        try:
            rows = await conn.fetch(
                "SELECT device_id, measurement, COUNT(*) AS samples "
                "FROM measurements WHERE site_id = $1 "
                "GROUP BY device_id, measurement "
                "ORDER BY device_id, measurement",
                site_id,
            )
        finally:
            await conn.close()
        return SiteDescription(
            site_id=site_id,
            pairs=[
                MeasurementPair(
                    device_id=str(r["device_id"]),
                    measurement=str(r["measurement"]),
                    samples=int(r["samples"]),
                )
                for r in rows
            ],
        )

    async def get_forecast(
        self,
        site_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
    ) -> ForecastSeries:
        """Eval doesn't seed forecasts; return an empty envelope."""
        _ = (start, end)
        return ForecastSeries(
            site_id=site_id,
            measurement=measurement,
            unit="",
            model_name="",
            model_version=0,
            points=[],
        )


@asynccontextmanager
async def seeded_server_client() -> AsyncGenerator[EvalServerClient]:
    """Spawn postgres + seed measurements + yield an EvalServerClient.

    Async-context so callers inside an asyncio loop (eval main()) can
    await the seed without re-entering asyncio.run(). Tears down the
    container on exit. Sets SITE_ID + SERVER_URL in process env so
    Agent() construction sees the same backend identity.
    """
    pwd = os.environ.get("POSTGRES_PASSWORD", "evalpw")
    with start_postgres(password=pwd, image="postgres:15") as pg:
        await _seed(pg.url)
        os.environ["SITE_ID"] = EVAL_SITE_ID
        os.environ["SERVER_URL"] = "http://eval-fake"
        yield EvalServerClient(postgres_url=pg.url)


async def _seed(db_url: str) -> None:
    """Create measurements + insert ~72h of synthetic data per device."""
    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute("""
            CREATE TABLE measurements (
                ts          timestamptz NOT NULL,
                site_id     text        NOT NULL,
                device_id   text        NOT NULL,
                measurement text        NOT NULL,
                unit        text,
                value       jsonb       NOT NULL
            );
            CREATE INDEX ON measurements
                (site_id, device_id, measurement, ts DESC);
        """)
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        rows: list[tuple[datetime, str, str, str, str | None, str]] = []
        for device in _DEVICES:
            for hr in range(72):
                ts = now - timedelta(hours=71 - hr)
                soc = 50.0 + 30.0 * (1.0 if hr % 4 < 2 else -1.0)
                rows.append(
                    (ts, EVAL_SITE_ID, device, "state_of_charge", "%", json.dumps(soc))
                )
        for device, status in zip(_DEVICES, ("alarm", "ok", "warn"), strict=True):
            rows.append((now, EVAL_SITE_ID, device, "status", None, json.dumps(status)))
        await conn.executemany(
            "INSERT INTO measurements "
            "(ts, site_id, device_id, measurement, unit, value) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            rows,
        )
        log.info("eval seed: %d rows into measurements", len(rows))
    finally:
        await conn.close()
