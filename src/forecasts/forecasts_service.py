"""asyncpg-backed read of the `forecasts` table.

Table is owned by ems-analyst-model's score+write step. This service
only reads. Empty windows return an envelope with empty points and a
sentinel model_name/version so the JSON shape stays stable.

Forecasts are keyed by `settlement_point` (the ERCOT market hub the
model predicts), NOT by customer site_id. The controller resolves the
requested site → its settlement_point via the deploy's cfg.
"""

import logging
import os
from datetime import datetime

from src.db import connect

from .dto import ForecastPoint, ForecastSeries

log = logging.getLogger(__name__)

_TIMESERIES_URL_ENV: str = "TIMESERIES_URL"


class ForecastsService:
    """Read forecast rows for one settlement_point + measurement in a window."""

    def __init__(self, postgres_url: str | None = None) -> None:
        """Optional URL override for tests; production reads env per-request."""
        self._postgres_url = postgres_url

    async def get(
        self,
        site_id: str,
        settlement_point: str,
        measurement: str,
        start: datetime,
        end: datetime,
    ) -> ForecastSeries:
        """Return forecast points in [start, end] ordered by forecast_for ASC.

        Query is by `settlement_point` (the market hub). `site_id` is
        only echoed back in the response so the HMI sees the site it
        asked for.

        If multiple model_names cover the window, keep the rows for
        whichever model_name sorts first — one forecast surface per
        (settlement_point, measurement) to start.
        """
        url = self._postgres_url or os.environ[_TIMESERIES_URL_ENV]
        async with connect(url) as conn:
            rows = await conn.fetch(
                "SELECT forecast_for, unit, value, model_name, model_version "
                "FROM forecasts "
                "WHERE settlement_point = $1 AND measurement = $2 "
                "  AND forecast_for BETWEEN $3 AND $4 "
                "ORDER BY model_name ASC, forecast_for ASC",
                settlement_point,
                measurement,
                start,
                end,
            )
        if not rows:
            return ForecastSeries(
                site_id=site_id,
                settlement_point=settlement_point,
                measurement=measurement,
                unit="",
                model_name="",
                model_version=0,
                points=[],
            )
        first = rows[0]
        model_name = str(first["model_name"])
        model_rows = [r for r in rows if r["model_name"] == model_name]
        points = [
            ForecastPoint(forecast_for=r["forecast_for"], value=r["value"])
            for r in model_rows
        ]
        return ForecastSeries(
            site_id=site_id,
            settlement_point=settlement_point,
            measurement=measurement,
            unit=str(first["unit"]),
            model_name=model_name,
            model_version=int(first["model_version"]),
            points=points,
        )
