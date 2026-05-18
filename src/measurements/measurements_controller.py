"""GET /sites/{site_id}/measurements — hourly-bucketed timeseries reads."""

from datetime import datetime

from classy_fastapi import Routable, get

from .dto import Aggregation, MeasurementSeries
from .measurements_service import MeasurementsService


class MeasurementsController(Routable):
    """Routes a bucketed measurement query through to MeasurementsService."""

    def __init__(self, service: MeasurementsService) -> None:
        super().__init__()
        self.service = service

    @get(
        "/sites/{site_id}/measurements",
        response_model=MeasurementSeries,
        tags=["Measurements"],
        responses={200: {"description": "Hourly-bucketed gap-filled series"}},
    )
    async def list_measurements(
        self,
        site_id: str,
        device_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
        aggregation: Aggregation = "mean",
    ) -> MeasurementSeries:
        """Return bucketed (ts, value|None) points for the site+device."""
        return await self.service.get(
            site_id=site_id,
            device_id=device_id,
            measurement=measurement,
            start=start,
            end=end,
            aggregation=aggregation,
        )
