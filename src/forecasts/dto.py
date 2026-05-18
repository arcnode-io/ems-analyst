"""DTOs for /sites/{id}/forecast responses.

Mirrors the forecasts table written by ems-analyst-model.score —
model_name + model_version are surfaced so callers can correlate a
forecast back to a specific registered model artifact.
"""

from datetime import datetime

from pydantic import BaseModel


class ForecastPoint(BaseModel):
    """One (forecast_for, value) prediction."""

    forecast_for: datetime
    value: float


class ForecastSeries(BaseModel):
    """Response envelope — predictions for one site+measurement."""

    site_id: str
    measurement: str
    unit: str
    model_name: str
    model_version: int
    points: list[ForecastPoint]
