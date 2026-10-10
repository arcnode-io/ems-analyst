"""Pure forecast↔actual error arithmetic — no I/O, no LLM.

`compute_forecast_accuracy` takes already-fetched series and returns
deterministic error stats: this is the root-cause fix for the model
trying (and failing) to eyeball a forecast-vs-actual comparison itself
across several separate tool calls. Same split as dispatch_explain.py:
pure stats here, fetch + chart-shaping in
`compare_forecast_artifact.py`.
"""

from datetime import datetime

from pydantic import BaseModel


class ForecastAccuracyStats(BaseModel):
    """Deterministic forecast-vs-actual error stats over the overlap window.

    `mean_bias` is signed (actual - forecast): positive means the
    market ran hotter than predicted, negative means the forecast
    overshot. `mae` (mean absolute error) is always non-negative — the
    size of the miss regardless of direction.
    """

    hours_compared: int
    forecast_avg: float
    actual_avg: float
    mean_bias: float
    mae: float
    max_abs_error: float
    max_error_at: datetime


def compute_forecast_accuracy(
    forecast: dict[datetime, float],
    actual: dict[datetime, float],
) -> ForecastAccuracyStats | None:
    """Error stats over the hours both series cover.

    `None` means no overlapping hour — not zero error. Hours where
    only one series has data (e.g. the forecast extends past what's
    been measured yet) are excluded rather than treated as a zero.
    """
    common = sorted(set(forecast) & set(actual))
    if not common:
        return None
    errors = {ts: actual[ts] - forecast[ts] for ts in common}
    abs_errors = {ts: abs(e) for ts, e in errors.items()}
    max_error_at = max(abs_errors, key=lambda ts: abs_errors[ts])
    return ForecastAccuracyStats(
        hours_compared=len(common),
        forecast_avg=sum(forecast[ts] for ts in common) / len(common),
        actual_avg=sum(actual[ts] for ts in common) / len(common),
        mean_bias=sum(errors.values()) / len(common),
        mae=sum(abs_errors.values()) / len(common),
        max_abs_error=abs_errors[max_error_at],
        max_error_at=max_error_at,
    )
