"""compare_forecast_to_actual tool — forecast vs. settled price, deterministic.

Built because the model consistently burned 4-5+ tool calls (describe_site,
get_forecast, get_market_data, query_markets, repeats) trying to eyeball
this comparison itself and still didn't synthesize an answer before
hitting the turn's tool-call budget. Same fix shape as explain_dispatch:
fetch both series, align, compute the error stats server-side, hand the
model one number-filled sentence it can answer from directly.

Single forecast surface exists today (dam_lmp_price @ HB_NORTH, see
forecasts table) against this site's own dam_clearing_price_usd_per_mwh
actuals — hardcoded pairing, not a generic N-measurement comparator,
since there's exactly one real pairing to compare. Add parameters if
a second forecast surface ships.
"""

from datetime import UTC, datetime, timedelta
from typing import Final

from pydantic_ai import RunContext

from ..isotime import iso_z
from ..schemas import AnalystArtifact, LineSpec
from ..server_client import ServerClient
from ._common import _TelemetryDeps, _error_artifact, _fmt_window, _parse_window
from .dispatch_explain_artifact import _DAM_PRICE_M, _MARKET_DEVICE_ID
from .forecast_accuracy import ForecastAccuracyStats, compute_forecast_accuracy
from .site_analytics import _bucketed_series

_FORECAST_MEASUREMENT: Final[str] = "dam_lmp_price"


async def build_compare_forecast(
    client: ServerClient, window: timedelta
) -> tuple[list[AnalystArtifact], ForecastAccuracyStats | None]:
    """One overlaid line chart (forecast + actual) + the error stats behind it.

    Retrospective window (end=now, start=now-window) — "how did the
    forecast do" asks about hours that have already settled, the
    opposite direction from get_forecast's forward-looking default.
    """
    end = datetime.now(UTC)
    start = end - window
    forecast_series = await client.get_forecast(
        measurement=_FORECAST_MEASUREMENT, start=start, end=end
    )
    if not forecast_series.points:
        return [
            _error_artifact(
                "not_found",
                f"No {_FORECAST_MEASUREMENT} forecast over the last "
                f"{_fmt_window(window)}.",
            )
        ], None
    forecast = {p.forecast_for: p.value for p in forecast_series.points}
    actual = await _bucketed_series(client, _MARKET_DEVICE_ID, _DAM_PRICE_M, start, end)
    stats = compute_forecast_accuracy(forecast, actual)
    if stats is None:
        return [
            _error_artifact(
                "not_found",
                f"Forecast and actual data don't overlap in the last "
                f"{_fmt_window(window)}.",
            )
        ], None
    spec = LineSpec.model_validate(
        {
            "title": f"Forecast vs actual DAM price, last {_fmt_window(window)}",
            "xAxis": {"label": "Time", "kind": "time"},
            "yAxis": {"label": "Price", "unit": "$/MWh"},
            "series": [
                {
                    "label": "forecast",
                    "points": [
                        {"x": ts.isoformat().replace("+00:00", "Z"), "y": v}
                        for ts, v in sorted(forecast.items())
                    ],
                },
                {
                    "label": "actual",
                    "points": [
                        {"x": ts.isoformat().replace("+00:00", "Z"), "y": v}
                        for ts, v in sorted(actual.items())
                    ],
                },
            ],
            "dataAsOf": iso_z(),
            "note": (
                f"{stats.hours_compared}h compared, mean bias "
                f"${stats.mean_bias:+.2f}/MWh, MAE ${stats.mae:.2f}/MWh"
            ),
        }
    )
    art = AnalystArtifact.model_validate(
        {"kind": "line", "spec": spec.model_dump(by_alias=True)}
    )
    return [art], stats


async def compare_forecast_to_actual(
    ctx: RunContext[_TelemetryDeps],
    window: str = "24h",
) -> str:
    """How the published day-ahead price forecast compared to actual — deterministic.

    For "how did the forecast compare to actual" / "how accurate was
    the forecast" questions, call this instead of fetching get_forecast
    and get_market_data separately and reasoning out the difference —
    it aligns both series by hour and returns the bias/MAE directly.
    One call, not several.

    Args:
        window: ISO-8601 duration ("PT24H") or shorthand ("24h","7d") —
            looks BACKWARD from now (opposite direction from
            get_forecast's default), since this compares against
            already-settled actuals.
    """
    td = _parse_window(window)
    client = ctx.deps.server
    assert isinstance(client, ServerClient)
    artifacts, stats = await build_compare_forecast(client, td)
    ctx.deps.artifacts.extend(artifacts)
    if stats is None:
        return f"No overlapping forecast/actual data over the last {window}."
    direction = "hotter" if stats.mean_bias > 0 else "cooler"
    return (
        f"Over the last {stats.hours_compared}h, actual DAM price ran "
        f"{direction} than forecast on average: forecast avg "
        f"${stats.forecast_avg:.2f}/MWh vs actual avg ${stats.actual_avg:.2f}/MWh "
        f"(mean bias ${stats.mean_bias:+.2f}/MWh, MAE ${stats.mae:.2f}/MWh). "
        f"Largest miss ${stats.max_abs_error:.2f}/MWh at "
        f"{stats.max_error_at:%Y-%m-%d %H:%M}."
    )
