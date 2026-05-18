"""Forecast builder + RunContext wrapper — reads the published model output.

ems-analyst-model writes per-site forecasts into the `forecasts` table
nightly; server exposes them at /sites/{id}/forecast. The agent never
touches MLflow at runtime — it just reads the curve.
"""

from datetime import UTC, datetime, timedelta

from pydantic_ai import RunContext

from ..schemas import AnalystArtifact, LineSpec
from ..server_client import ServerClient
from .telemetry import _TelemetryDeps, _error_artifact, _now, _parse_window


async def build_forecast(
    client: ServerClient,
    site_id: str,
    measurement: str,
    window: timedelta,
) -> AnalystArtifact:
    """Bucketed forecast via server's /forecast; empty → error artifact."""
    now = datetime.now(UTC)
    end = now + window
    series = await client.get_forecast(
        site_id=site_id, measurement=measurement, start=now, end=end
    )
    if not series.points:
        return _error_artifact(
            "not_found",
            f"No forecast for {measurement} at {site_id} in the next {window}.",
        )
    points = [
        {"x": p.forecast_for.isoformat().replace("+00:00", "Z"), "y": p.value}
        for p in series.points
    ]
    # Lineage in the title so the user knows which model published the
    # curve they're looking at.
    title = (
        f"{measurement} forecast — next {window} "
        f"({series.model_name} v{series.model_version})"
    )
    spec = LineSpec.model_validate(
        {
            "title": title,
            "xAxis": {"label": "Time", "kind": "time"},
            "yAxis": {"label": measurement, "unit": series.unit},
            "series": [{"label": "forecast", "points": points}],
            "dataAsOf": _now(),
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "line", "spec": spec.model_dump(by_alias=True)}
    )


async def get_forecast(
    ctx: RunContext[_TelemetryDeps],
    measurement: str,
    window: str = "PT24H",
) -> str:
    """Published forecast curve for a measurement at this site.

    The forecast comes from ems-analyst-model's nightly score step;
    server exposes it at /forecast. Returns a line chart with the
    publishing model + version in the title.

    Args:
        measurement: Forecast measurement name (e.g. dam_lmp_price).
        window: ISO-8601 duration ("PT24H") or shorthand ("24h","7d").
    """
    td = _parse_window(window)
    client = ctx.deps.server
    assert isinstance(client, ServerClient)
    art = await build_forecast(client, ctx.deps.site_id, measurement, td)
    ctx.deps.artifacts.append(art)
    if art.kind == "error":
        return f"No forecast for {measurement} over {window}."
    return f"Returned forecast curve for {measurement} (window={window})."
