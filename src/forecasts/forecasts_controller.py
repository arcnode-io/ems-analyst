"""GET /sites/{site_id}/forecast — deterministic forecast reads.

The forecast is market-keyed (settlement_point), but the HMI contract
is site-keyed (`/sites/{site_id}/forecast`). The controller holds the
deploy's settlement_point (resolved from cfg by the module) and bridges
the two — HMI keeps asking by site, the query runs by hub.
"""

from datetime import datetime

from classy_fastapi import Routable, get

from .dto import ForecastSeries
from .forecasts_service import ForecastsService


class ForecastsController(Routable):
    """Routes a windowed forecast query through to ForecastsService."""

    def __init__(self, service: ForecastsService, settlement_point: str) -> None:
        super().__init__()
        self.service = service
        self.settlement_point = settlement_point

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
        """Return forecast points for the site in [start, end].

        The site resolves to this deploy's settlement_point; the query
        runs against that hub.
        """
        return await self.service.get(
            site_id=site_id,
            settlement_point=self.settlement_point,
            measurement=measurement,
            start=start,
            end=end,
        )
