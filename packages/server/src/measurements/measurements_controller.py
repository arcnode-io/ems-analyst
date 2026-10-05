"""GET /analyst/measurements (+ /measurements alias) — bucketed timeseries reads.

Single-site deploy: the server knows its own site_id from cfg, so the
path carries no site segment. The controller holds the deploy site_id.

Two paths, one handler: the HMI's nginx only proxies /analyst/* (no
path-stripping — the same reason /analyst/chat lives at that path), so
a same-origin GET /measurements from the HMI would land on its own SPA
instead of here. /measurements stays too since the agent calls it
directly, in-process, with no nginx in between.
"""

from datetime import datetime
from typing import Annotated

from classy_fastapi import Routable, get
from fastapi import Query

from .dto import Aggregation, LatestValuesResponse, MeasurementSeries
from .measurements_service import MeasurementsService


class MeasurementsController(Routable):
    """Routes a bucketed measurement query through to MeasurementsService."""

    def __init__(self, service: MeasurementsService, site_id: str) -> None:
        super().__init__()
        self.service = service
        self.site_id = site_id

    @get(
        "/analyst/measurements",
        response_model=MeasurementSeries,
        tags=["Measurements"],
        responses={200: {"description": "Bucketed gap-filled series"}},
    )
    async def list_measurements(
        self,
        device_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
        aggregation: Aggregation = "mean",
        bucket_s: int = 3600,
    ) -> MeasurementSeries:
        """Return bucketed (ts, value|None) points for the deploy site+device."""
        return await self._get(
            device_id, measurement, start, end, aggregation, bucket_s
        )

    @get(
        "/measurements",
        response_model=MeasurementSeries,
        tags=["Measurements"],
        responses={200: {"description": "Bucketed gap-filled series"}},
        include_in_schema=False,
    )
    async def list_measurements_unprefixed(
        self,
        device_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
        aggregation: Aggregation = "mean",
        bucket_s: int = 3600,
    ) -> MeasurementSeries:
        """Alias of /analyst/measurements — the agent calls this directly, no nginx."""
        return await self._get(
            device_id, measurement, start, end, aggregation, bucket_s
        )

    async def _get(
        self,
        device_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
        aggregation: Aggregation,
        bucket_s: int,
    ) -> MeasurementSeries:
        return await self.service.get(
            site_id=self.site_id,
            device_id=device_id,
            measurement=measurement,
            start=start,
            end=end,
            aggregation=aggregation,
            bucket_s=bucket_s,
        )

    @get(
        "/analyst/measurements/latest",
        response_model=LatestValuesResponse,
        tags=["Measurements"],
        responses={200: {"description": "Latest value per requested pair"}},
    )
    async def list_latest(
        self,
        device_ids: Annotated[list[str], Query()],
        measurements: Annotated[list[str], Query()],
    ) -> LatestValuesResponse:
        """Bulk latest-value lookup — one call for many (device, measurement) pairs.

        For a rollup over many devices (e.g. device-status across a whole
        fleet) rather than one query per device.
        """
        return await self._get_latest(device_ids, measurements)

    @get(
        "/measurements/latest",
        response_model=LatestValuesResponse,
        tags=["Measurements"],
        responses={200: {"description": "Latest value per requested pair"}},
        include_in_schema=False,
    )
    async def list_latest_unprefixed(
        self,
        device_ids: Annotated[list[str], Query()],
        measurements: Annotated[list[str], Query()],
    ) -> LatestValuesResponse:
        """Alias of /analyst/measurements/latest — the agent calls this directly."""
        return await self._get_latest(device_ids, measurements)

    async def _get_latest(
        self, device_ids: list[str], measurements: list[str]
    ) -> LatestValuesResponse:
        values = await self.service.get_latest(
            site_id=self.site_id, device_ids=device_ids, measurements=measurements
        )
        return LatestValuesResponse(site_id=self.site_id, values=values)
