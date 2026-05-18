"""GET /sites/{site_id}/measurements — deterministic timeseries reads."""

from datetime import datetime

from classy_fastapi import Routable, get

from .dto import MeasurementSeries
from .measurements_service import MeasurementsService


class MeasurementsController(Routable):
    """Routes a windowed measurement query through to MeasurementsService."""

    def __init__(self, service: MeasurementsService) -> None:
        super().__init__()
        self.service = service

    @get(
        "/sites/{site_id}/measurements",
        response_model=MeasurementSeries,
        tags=["Measurements"],
        responses={200: {"description": "Series of (ts, value) points"}},
    )
    async def list_measurements(
        self,
        site_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
    ) -> MeasurementSeries:
        """Return measurement points for the site in [start, end]."""
        return await self.service.get(
            site_id=site_id, measurement=measurement, start=start, end=end
        )
