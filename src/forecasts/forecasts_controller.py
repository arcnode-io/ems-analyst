"""GET /sites/{site_id}/forecast — deterministic forecast reads."""

from datetime import datetime

from classy_fastapi import Routable, get

from .dto import ForecastSeries
from .forecasts_service import ForecastsService


class ForecastsController(Routable):
    """Routes a windowed forecast query through to ForecastsService."""

    def __init__(self, service: ForecastsService) -> None:
        super().__init__()
        self.service = service

    @get(
        "/sites/{site_id}/forecast",
        response_model=ForecastSeries,
        tags=["Forecasts"],
        responses={200: {"description": "Series of (forecast_for, value) points"}},
    )
    async def list_forecast(
        self,
        site_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
    ) -> ForecastSeries:
        """Return forecast points for the site in [start, end]."""
        return await self.service.get(
            site_id=site_id, measurement=measurement, start=start, end=end
        )
