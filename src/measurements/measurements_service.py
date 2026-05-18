"""asyncpg-backed read of the canonical `measurements` table.

Mirrors ConversationStore — raw asyncpg, no migration framework. The
table is owned by platform-api's telemetry_writer; this service only
reads. Value cast to float at the SQL boundary so the DTO can stay
strongly-typed; non-numeric measurements (bool sensors) need a separate
endpoint when that need shows up.
"""

import logging
import os
from datetime import datetime

import asyncpg

from .dto import MeasurementPoint, MeasurementSeries

log = logging.getLogger(__name__)

_TIMESERIES_URL_ENV: str = "TIMESERIES_URL"


class MeasurementsService:
    """Read time-windowed points from the canonical measurements table."""

    def __init__(self, postgres_url: str | None = None) -> None:
        """Optional URL override for tests; production reads env per-request."""
        self._postgres_url = postgres_url

    async def get(
        self,
        site_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
    ) -> MeasurementSeries:
        """Return points in [start, end] for one site+measurement, ts ASC.

        Empty rows → empty points list; the unit defaults to "" so the
        envelope stays valid for the no-data case.
        """
        url = self._postgres_url or os.environ[_TIMESERIES_URL_ENV]
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch(
                "SELECT ts, unit, (value::text)::float AS value "
                "FROM measurements "
                "WHERE site_id = $1 AND measurement = $2 "
                "  AND ts BETWEEN $3 AND $4 "
                "ORDER BY ts ASC",
                site_id,
                measurement,
                start,
                end,
            )
        finally:
            await conn.close()
        unit = str(rows[0]["unit"]) if rows else ""
        points = [MeasurementPoint(ts=r["ts"], value=r["value"]) for r in rows]
        return MeasurementSeries(
            site_id=site_id, measurement=measurement, unit=unit, points=points
        )
