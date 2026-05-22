"""Forecast builder + RunContext wrapper — reads the published model output.

ems-analyst-model writes per-site forecasts into the `forecasts` table
nightly; server exposes them at /forecast. The agent never touches
MLflow at runtime — it just reads the curve.
"""

from datetime import UTC, datetime, timedelta

from pydantic_ai import RunContext

from ..isotime import iso_z
from ..schemas import AnalystArtifact, LineSpec
from ..server_client import ServerClient
from ._common import (
    Render,
    _TelemetryDeps,
    _error_artifact,
    _fmt_window,
    _parse_window,
    _to_table,
)


async def build_forecast(
    client: ServerClient,
    measurement: str,
    window: timedelta,
) -> AnalystArtifact:
    """Bucketed forecast via server's /forecast; empty → error artifact."""
    now = datetime.now(UTC)
    end = now + window
    series = await client.get_forecast(measurement=measurement, start=now, end=end)
    if not series.points:
        return _error_artifact(
            "not_found",
            f"No forecast for {measurement} in the next {_fmt_window(window)}.",
        )
    points = [
        {"x": p.forecast_for.isoformat().replace("+00:00", "Z"), "y": p.value}
        for p in series.points
    ]
    # Lineage in the title so the user knows which model published the
    # curve they're looking at.
    title = (
        f"{measurement} forecast — next {_fmt_window(window)} "
        f"({series.model_name} v{series.model_version})"
    )
    ys = [p.value for p in series.points]
    note = f"forecast {min(ys):g}-{max(ys):g} {series.unit}, opens at {ys[0]:g}"
    spec = LineSpec.model_validate(
        {
            "title": title,
            "xAxis": {"label": "Time", "kind": "time"},
            "yAxis": {"label": measurement, "unit": series.unit},
            "series": [{"label": "forecast", "points": points}],
            "dataAsOf": iso_z(),
            "note": note,
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "line", "spec": spec.model_dump(by_alias=True)}
    )


async def get_forecast(
    ctx: RunContext[_TelemetryDeps],
    measurement: str,
    window: str = "PT24H",
    render: Render = "chart",
) -> str:
    """Published forecast curve for a measurement at this site.

    The forecast comes from ems-analyst-model's nightly score step;
    server exposes it at /forecast.

    Args:
        measurement: Forecast measurement name (e.g. dam_lmp_price).
        window: ISO-8601 duration ("PT24H") or shorthand ("24h","7d").
        render: "chart" for a line chart, "table" for a data table —
            use "table" when the user asks for the numbers as a table.
    """
    td = _parse_window(window)
    client = ctx.deps.server
    assert isinstance(client, ServerClient)
    art = await build_forecast(client, measurement, td)
    if render == "table":
        art = _to_table(art)
    ctx.deps.artifacts.append(art)
    if art.kind == "error":
        return f"No forecast for {measurement} over {window}."
    return f"Returned forecast {render} for {measurement} (window={window})."
