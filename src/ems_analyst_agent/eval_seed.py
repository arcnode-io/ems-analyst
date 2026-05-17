"""Postgres testcontainer + measurements seed for the eval harnesses.

Both eval.py and eval_mcp.py need a real TimeseriesClient so the
telemetry tools work. This module spins up a vanilla Postgres
container, seeds public.measurements with realistic site data, and
returns a TimeseriesClient pointed at it.

Caller wraps in ExitStack so the container tears down with the run.
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

from .timeseries import TimeseriesClient

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


@asynccontextmanager
async def seeded_timeseries_client() -> AsyncGenerator[TimeseriesClient]:
    """Spawn postgres + seed measurements + yield a TimeseriesClient.

    Async-context so callers inside an asyncio loop (eval main()) can
    await the seed without re-entering asyncio.run(). Tears down the
    container on exit. Sets TIMESERIES_URL + SITE_ID in process env so
    anything else relying on those (Agent) sees the same backend.
    """
    pwd = os.environ.get("POSTGRES_PASSWORD", "evalpw")
    with start_postgres(password=pwd, image="postgres:15") as pg:
        await _seed(pg.url)
        os.environ["TIMESERIES_URL"] = pg.url
        os.environ["SITE_ID"] = EVAL_SITE_ID
        yield TimeseriesClient(postgres_url=pg.url)


async def _seed(db_url: str) -> None:
    """Create public.measurements + insert ~72h of synthetic data per device."""
    conn = await asyncpg.connect(db_url)
    try:
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
        rows: list[tuple[datetime, str, str, str, str | None, str]] = []
        # 72 hourly SoC points per device, sinusoidal-ish so different aggregations differ.
        for device in _DEVICES:
            for hr in range(72):
                ts = now - timedelta(hours=71 - hr)
                soc = 50.0 + 30.0 * (1.0 if hr % 4 < 2 else -1.0)
                rows.append(
                    (ts, EVAL_SITE_ID, device, "state_of_charge", "%", json.dumps(soc))
                )
        # Latest status per device — one alarm, one warn, one ok so list_devices_where
        # has filterable variety.
        for device, status in zip(_DEVICES, ("alarm", "ok", "warn"), strict=True):
            rows.append((now, EVAL_SITE_ID, device, "status", None, json.dumps(status)))
        await conn.executemany(
            "INSERT INTO public.measurements "
            "(ts, site_id, device_id, measurement, unit, value) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            rows,
        )
        log.info("eval seed: %d rows into public.measurements", len(rows))
    finally:
        await conn.close()
