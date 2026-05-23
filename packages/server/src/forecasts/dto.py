"""DTOs for GET /forecast responses.

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
    """Response envelope — predictions for one site+measurement.

    `site_id` is the customer site the caller asked for.
    `settlement_point` is the ERCOT market hub the forecast is actually
    keyed on — surfaced so the HMI can show which hub drives the curve.
    """

    site_id: str
    settlement_point: str
    measurement: str
    unit: str
    model_name: str
    model_version: int
    points: list[ForecastPoint]
