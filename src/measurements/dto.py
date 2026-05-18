"""DTOs for /sites/{id}/measurements responses.

Shape matches the agent's expected return so the agent's REST tool can
deserialize directly. Plain (ts, value) points under a measurement
envelope carrying site_id + unit metadata.
"""

from datetime import datetime

from pydantic import BaseModel


class MeasurementPoint(BaseModel):
    """One (ts, value) reading."""

    ts: datetime
    value: float


class MeasurementSeries(BaseModel):
    """Response envelope — series of points for one site+measurement."""

    site_id: str
    measurement: str
    unit: str
    points: list[MeasurementPoint]
