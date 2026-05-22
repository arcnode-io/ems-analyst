"""asyncpg-backed read of the canonical `measurements` table.

Hourly-bucketed, gap-filled timeseries — same shape the agent's old
TimeseriesClient.query_hourly returned. `generate_series` + LEFT JOIN
yields a row for every hour in the window even when no measurements
landed there (chart renderers render the gap as a break in the line).
"""

import logging
import os
from datetime import datetime

from src.db import connect

from .dto import Aggregation, MeasurementPoint, MeasurementSeries

log = logging.getLogger(__name__)

_TIMESERIES_URL_ENV: str = "TIMESERIES_URL"

# Reason: aggregation is constrained to a whitelist below; the f-string
# substitution is safe. Bandit and ruff can't see that.
_AGG_SQL: dict[Aggregation, str] = {
    "mean": "AVG((value::text)::float)",
    "max": "MAX((value::text)::float)",
    "min": "MIN((value::text)::float)",
    "last": "(ARRAY_AGG((value::text)::float ORDER BY ts DESC))[1]",
}


class MeasurementsService:
    """Hourly-bucketed reads from the canonical measurements table."""

    def __init__(self, postgres_url: str | None = None) -> None:
        """Optional URL override for tests; production reads env per-request."""
        self._postgres_url = postgres_url

    async def get(
        self,
        site_id: str,
        device_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
        aggregation: Aggregation = "mean",
    ) -> MeasurementSeries:
        """Return hourly-bucketed gap-filled series in [start, end].

        Empty windows still get a row per hour with value=None so
        downstream chart renderers see the gap. Unit comes from the
        latest matching row (falls back to "" when window is empty).
        """
        url = self._postgres_url or os.environ[_TIMESERIES_URL_ENV]
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
                WHERE site_id = $3
                  AND device_id = $4
                  AND measurement = $5
                  AND ts >= $1::timestamptz
                  AND ts <  $2::timestamptz
                GROUP BY bucket
            )
            SELECT b.ts, a.y, a.unit
            FROM buckets b
            LEFT JOIN agg a ON a.bucket = b.ts
            ORDER BY b.ts
        """  # noqa: S608  # nosec B608
        async with connect(url) as conn:
            rows = await conn.fetch(sql, start, end, site_id, device_id, measurement)
        # Find unit from first non-null bucket (gap-filled rows have unit=None).
        unit = ""
        for r in rows:
            if r["unit"] is not None:
                unit = str(r["unit"])
                break
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
