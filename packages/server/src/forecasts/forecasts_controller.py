"""GET /forecast — deterministic forecast reads.

Single-site deploy: the controller holds both the deploy's site_id
(echoed in the response) and its settlement_point (the ERCOT hub the
forecast is keyed on). Neither is in the path.
"""

from datetime import datetime

from classy_fastapi import Routable, get

from .dto import ForecastSeries
from .forecasts_service import ForecastsService


class ForecastsController(Routable):
    """Routes a windowed forecast query through to ForecastsService."""

    def __init__(
        self, service: ForecastsService, site_id: str, settlement_point: str
    ) -> None:
        super().__init__()
        self.service = service
        self.site_id = site_id
        self.settlement_point = settlement_point

    @get(
        "/forecast",
        response_model=ForecastSeries,
        tags=["Forecasts"],
        responses={200: {"description": "Series of (forecast_for, value) points"}},
    )
    async def list_forecast(
        self,
        measurement: str,
        start: datetime,
        end: datetime,
    ) -> ForecastSeries:
        """Return forecast points for the deploy site in [start, end].

        Query runs against the deploy's settlement_point; the response
        echoes the deploy site_id.
        """
        return await self.service.get(
            site_id=self.site_id,
            settlement_point=self.settlement_point,
            measurement=measurement,
            start=start,
            end=end,
        )
