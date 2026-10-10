"""compare_forecast_to_actual tool — forecast vs. settled price, deterministic.

Built because the model consistently burned 4-5+ tool calls (describe_site,
get_forecast, get_market_data, query_markets, repeats) trying to eyeball
this comparison itself and still didn't synthesize an answer before
hitting the turn's tool-call budget. Same fix shape as explain_dispatch:
fetch both series, align, compute the error stats server-side, hand the
model one number-filled sentence it can answer from directly.

"Actual" comes from gridstatus.io (ERCOT DAM SPP), not the site's own
historian: the historian has no market-price-publishing device on any
deployment seen so far — real settlement price is external ISO data,
not something a site's own meters produce. See [[forecast-no-shortcuts]].

Single forecast surface exists today (dam_lmp_price @ HB_NORTH, see
forecasts table) against ERCOT's HB_NORTH day-ahead SPP — hardcoded
pairing, not a generic N-measurement comparator, since there's exactly
one real pairing to compare. Add parameters if a second forecast
surface ships.
"""

from datetime import UTC, datetime, timedelta
from typing import Final

from pydantic_ai import RunContext

from ..isotime import iso_z
from ..schemas import AnalystArtifact, LineSpec
from ..server_client import ServerClient
from ._common import _TelemetryDeps, _error_artifact, _fmt_window, _parse_window
from .forecast_accuracy import ForecastAccuracyStats, compute_forecast_accuracy
from .market_prices import fetch_market_series

_FORECAST_MEASUREMENT: Final[str] = "dam_lmp_price"
_ACTUAL_DATASET: Final[str] = "ercot_spp_day_ahead_hourly"
_ACTUAL_LOCATION: Final[str] = "HB_NORTH"
_ACTUAL_TS_COLUMN: Final[str] = "interval_start_utc"
_ACTUAL_VALUE_COLUMN: Final[str] = "spp"
_SYNTHETIC_CAVEAT: Final[str] = (
    "⚠ SYNTHETIC actual data (gridstatus.io unavailable) — "
    "comparison is illustrative, not real settlement."
)


async def build_compare_forecast(
    client: ServerClient, window: timedelta
) -> tuple[list[AnalystArtifact], ForecastAccuracyStats | None, bool]:
    """One overlaid line chart (forecast + actual) + the error stats behind it.

    Retrospective window (end=now, start=now-window) — "how did the
    forecast do" asks about hours that have already settled, the
    opposite direction from get_forecast's forward-looking default.

    The trailing bool is True when "actual" came from gridstatus's
    synthetic fallback rather than a real settlement — the RunContext
    wrapper needs it too, not just the chart note, so the LLM-visible
    sentence carries the same caveat.
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
        ], None, False
    forecast = {p.forecast_for: p.value for p in forecast_series.points}
    hours = max(int(window.total_seconds() // 3600) + 2, 1)
    actual_points = await fetch_market_series(
        dataset=_ACTUAL_DATASET,
        location=_ACTUAL_LOCATION,
        ts_column=_ACTUAL_TS_COLUMN,
        value_column=_ACTUAL_VALUE_COLUMN,
        start=start,
        end=end,
        limit=hours,
    )
    actual = {p.ts: p.value for p in actual_points}
    stats = compute_forecast_accuracy(forecast, actual)
    is_synthetic = any(p.is_synthetic for p in actual_points)
    if stats is None:
        return [
            _error_artifact(
                "not_found",
                f"Forecast and actual data don't overlap in the last "
                f"{_fmt_window(window)}.",
            )
        ], None, is_synthetic
    note = (
        f"{stats.hours_compared}h compared, mean bias "
        f"${stats.mean_bias:+.2f}/MWh, MAE ${stats.mae:.2f}/MWh"
    )
    if is_synthetic:
        note = f"{_SYNTHETIC_CAVEAT} {note}"
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
            "note": note,
        }
    )
    art = AnalystArtifact.model_validate(
        {"kind": "line", "spec": spec.model_dump(by_alias=True)}
    )
    return [art], stats, is_synthetic


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
    artifacts, stats, is_synthetic = await build_compare_forecast(client, td)
    ctx.deps.artifacts.extend(artifacts)
    if stats is None:
        return f"No overlapping forecast/actual data over the last {window}."
    direction = "hotter" if stats.mean_bias > 0 else "cooler"
    caveat = f"{_SYNTHETIC_CAVEAT} " if is_synthetic else ""
    return (
        f"{caveat}Over the last {stats.hours_compared}h, actual DAM price ran "
        f"{direction} than forecast on average: forecast avg "
        f"${stats.forecast_avg:.2f}/MWh vs actual avg ${stats.actual_avg:.2f}/MWh "
        f"(mean bias ${stats.mean_bias:+.2f}/MWh, MAE ${stats.mae:.2f}/MWh). "
        f"Largest miss ${stats.max_abs_error:.2f}/MWh at "
        f"{stats.max_error_at:%Y-%m-%d %H:%M}."
    )
