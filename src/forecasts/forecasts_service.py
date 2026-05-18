"""asyncpg-backed read of the `forecasts` table.

Table is owned by ems-analyst-model's score+write step. This service
only reads. Empty windows return an envelope with empty points and a
sentinel model_name/version so the JSON shape stays stable.
"""

import logging
import os
from datetime import datetime

import asyncpg

from .dto import ForecastPoint, ForecastSeries

log = logging.getLogger(__name__)

_TIMESERIES_URL_ENV: str = "TIMESERIES_URL"


class ForecastsService:
    """Read forecast rows for one site+measurement in a time window."""

    def __init__(self, postgres_url: str | None = None) -> None:
        """Optional URL override for tests; production reads env per-request."""
        self._postgres_url = postgres_url

    async def get(
        self,
        site_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
    ) -> ForecastSeries:
        """Return forecast points in [start, end] ordered by forecast_for ASC.

        If multiple model_names cover the window, we keep the rows for
        whichever model_name shows up first (lexicographic) — keep one
        forecast surface per (site, measurement) to start; we can pick
        an explicit model later if more than one ever co-exists.
        """
        url = self._postgres_url or os.environ[_TIMESERIES_URL_ENV]
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch(
                "SELECT forecast_for, unit, value, model_name, model_version "
                "FROM forecasts "
                "WHERE site_id = $1 AND measurement = $2 "
                "  AND forecast_for BETWEEN $3 AND $4 "
                "ORDER BY model_name ASC, forecast_for ASC",
                site_id,
                measurement,
                start,
                end,
            )
        finally:
            await conn.close()
        if not rows:
            return ForecastSeries(
                site_id=site_id,
                measurement=measurement,
                unit="",
                model_name="",
                model_version=0,
                points=[],
            )
        first = rows[0]
        model_name = str(first["model_name"])
        # Reason: ORDER BY model_name groups same-model rows contiguously;
        # filter to the first model_name's rows so we don't interleave
        # competing models in the same series.
        model_rows = [r for r in rows if r["model_name"] == model_name]
        points = [
            ForecastPoint(forecast_for=r["forecast_for"], value=r["value"])
            for r in model_rows
        ]
        return ForecastSeries(
            site_id=site_id,
            measurement=measurement,
            unit=str(first["unit"]),
            model_name=model_name,
            model_version=int(first["model_version"]),
            points=points,
        )
