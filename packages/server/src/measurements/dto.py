"""DTOs for GET /measurements responses.

Hourly-bucketed gap-filled series per (site, device, measurement).
Missing buckets surface as value=None so chart renderers can draw gaps.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Aggregation = Literal["mean", "max", "min", "last"]


class MeasurementPoint(BaseModel):
    """One bucketed point — value=None for empty buckets.

    Most measurements are numeric, but enum-typed ones (e.g. device
    `status`: ok/warn/alarm) publish a string value.
    """

    ts: datetime
    value: float | str | None


class MeasurementSeries(BaseModel):
    """Response envelope — bucketed series for one site+device+measurement."""

    site_id: str
    device_id: str
    measurement: str
    unit: str
    points: list[MeasurementPoint]
