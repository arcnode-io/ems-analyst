"""TimeseriesClient — portable SQL over measurements.

Schema (identical across Tiger / Aurora+pg_partman / self-hosted Timescale):

  CREATE TABLE measurements (
      ts          timestamptz,
      site_id     text,
      device_id   text,
      measurement text,
      unit        text,
      value       jsonb           -- polymorphic
  );
  CREATE INDEX ON measurements (site_id, device_id, measurement, ts DESC);

Portability rules (per platform-api contract):
- Vanilla Postgres SQL only — date_trunc(), window functions, generate_series().
- NO time_bucket() — Tiger + Timescale have it but defense (pg_partman) doesn't.
- Cast value: (value::text)::float for floats, (value::text)::bool for bools.

TIMESERIES_URL env var → connection. Same pattern as MemoryService.VECTOR_URL.
"""

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Final

import asyncpg

log = logging.getLogger(__name__)

_TIMESERIES_URL_ENV: Final[str] = "TIMESERIES_URL"


class TimeseriesClient:
    """asyncpg-backed measurements reader. Read-only, portable SQL."""

    def __init__(self, postgres_url: str) -> None:
        """Wrap a Postgres URL. Same shape as MemoryService."""
        self.postgres_url = postgres_url

    @classmethod
    def from_env(cls) -> "TimeseriesClient":
        """Read TIMESERIES_URL from process env."""
        return cls(postgres_url=os.environ[_TIMESERIES_URL_ENV])

    async def query_hourly(
        self,
        site_id: str,
        device_id: str,
        measurement: str,
        window: timedelta,
        aggregation: str = "mean",
    ) -> list[tuple[datetime, float | None]]:
        """Hourly-bucketed aggregation over the window. Returns (ts, value) tuples.

        aggregation: mean | max | min | last. Buckets via date_trunc('hour').
        Missing buckets in the window get y=None (no-data → HMI renders as —).
        """
        # Reason: aggregation is constrained to a whitelist via _AGG_SQL,
        # not user input; the f-string is safe. Bandit can't see that.
        agg_sql = _AGG_SQL[aggregation]
        end = datetime.now(UTC)
        start = end - window
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
                       {agg_sql} AS y
                FROM measurements
                WHERE site_id = $3
                  AND device_id = $4
                  AND measurement = $5
                  AND ts >= $1::timestamptz
                  AND ts <  $2::timestamptz
                GROUP BY bucket
            )
            SELECT b.ts, a.y
            FROM buckets b
            LEFT JOIN agg a ON a.bucket = b.ts
            ORDER BY b.ts
        """  # noqa: S608  # nosec B608
        conn = await asyncpg.connect(self.postgres_url)
        try:
            rows = await conn.fetch(sql, start, end, site_id, device_id, measurement)
        finally:
            await conn.close()
        return [(r["ts"], (None if r["y"] is None else float(r["y"]))) for r in rows]

    async def list_devices(
        self, site_id: str, status: list[str] | None = None
    ) -> list[dict[str, str | float | None]]:
        """Distinct device_ids at the site, with last-known status if available.

        Status comes from the latest 'status' measurement per device. Devices
        without any status measurement get status=None and are included unless
        a status filter is provided (in which case they're excluded).
        """
        sql = """
            WITH latest_status AS (
                SELECT DISTINCT ON (device_id)
                       device_id, (value::text) AS status
                FROM measurements
                WHERE site_id = $1 AND measurement = 'status'
                ORDER BY device_id, ts DESC
            )
            SELECT DISTINCT m.device_id,
                   ls.status
            FROM measurements m
            LEFT JOIN latest_status ls ON ls.device_id = m.device_id
            WHERE m.site_id = $1
            ORDER BY m.device_id
        """
        conn = await asyncpg.connect(self.postgres_url)
        try:
            rows = await conn.fetch(sql, site_id)
        finally:
            await conn.close()
        result: list[dict[str, str | float | None]] = [
            {"device": str(r["device_id"]), "status": _strip_quotes(r["status"])}
            for r in rows
        ]
        if status:
            return [r for r in result if r["status"] in status]
        return result

    async def describe_site(self, site_id: str) -> list[dict[str, str | int]]:
        """Distinct (device_id, measurement) pairs + sample count at the site.

        Lets the LLM discover what's actually in the historian before guessing
        measurement names. Returns rows like:
            {"device": "BESS-01", "measurement": "state_of_charge", "samples": 48}
        """
        conn = await asyncpg.connect(self.postgres_url)
        try:
            rows = await conn.fetch(
                "SELECT device_id, measurement, count(*) AS samples "
                "FROM measurements WHERE site_id = $1 "
                "GROUP BY device_id, measurement "
                "ORDER BY device_id, measurement",
                site_id,
            )
        finally:
            await conn.close()
        return [
            {
                "device": str(r["device_id"]),
                "measurement": str(r["measurement"]),
                "samples": int(r["samples"]),
            }
            for r in rows
        ]

    async def query_sum_over_window(
        self, site_id: str, measurement: str, window: timedelta
    ) -> float | None:
        """Total value of one measurement (any device at the site) over window.

        Used by build_energy_breakdown — one call per source measurement.
        Returns None when no rows match (HMI renders missing slice as —).
        """
        sql = """
            SELECT SUM((value::text)::float) AS total
            FROM measurements
            WHERE site_id = $1
              AND measurement = $2
              AND ts >= now() - $3::interval
        """
        conn = await asyncpg.connect(self.postgres_url)
        try:
            total = await conn.fetchval(sql, site_id, measurement, window)
        finally:
            await conn.close()
        return None if total is None else float(total)


# Aggregation expression injected into the bucketing CTE — keeps the
# SQL one query. value is jsonb → cast to text → float.
_AGG_SQL: dict[str, str] = {
    "mean": "AVG((value::text)::float)",
    "max": "MAX((value::text)::float)",
    "min": "MIN((value::text)::float)",
    "last": "(ARRAY_AGG((value::text)::float ORDER BY ts DESC))[1]",
}


def _strip_quotes(jsonb_text: str | None) -> str | None:
    """jsonb text strings come back wrapped in quotes; strip for prose use."""
    if jsonb_text is None:
        return None
    s = str(jsonb_text)
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s
