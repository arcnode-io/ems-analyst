"""GET /measurements — hourly-bucketed timeseries reads.

Single-site deploy: the server knows its own site_id from cfg, so the
path carries no site segment. The controller holds the deploy site_id.
"""

from datetime import datetime

from classy_fastapi import Routable, get

from .dto import Aggregation, MeasurementSeries
from .measurements_service import MeasurementsService


class MeasurementsController(Routable):
    """Routes a bucketed measurement query through to MeasurementsService."""

    def __init__(self, service: MeasurementsService, site_id: str) -> None:
        super().__init__()
        self.service = service
        self.site_id = site_id

    @get(
        "/measurements",
        response_model=MeasurementSeries,
        tags=["Measurements"],
        responses={200: {"description": "Hourly-bucketed gap-filled series"}},
    )
    async def list_measurements(
        self,
        device_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
        aggregation: Aggregation = "mean",
    ) -> MeasurementSeries:
        """Return bucketed (ts, value|None) points for the deploy site+device."""
        return await self.service.get(
            site_id=self.site_id,
            device_id=device_id,
            measurement=measurement,
            start=start,
            end=end,
            aggregation=aggregation,
        )
