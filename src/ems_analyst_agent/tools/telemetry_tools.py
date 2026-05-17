"""RunContext wrappers around telemetry builders.

Separated from telemetry.py to keep each file under the 200-line cap.
The Agent imports these four and registers them as Tool() instances.
"""

from typing import Literal

from pydantic_ai import RunContext

from ..timeseries import TimeseriesClient
from .telemetry import (
    _TelemetryDeps,
    _parse_window,
    build_device_list,
    build_energy_breakdown_stub,
    build_markets_stub,
    build_site_description,
    build_timeseries,
)


async def query_timeseries(
    ctx: RunContext[_TelemetryDeps],
    device_id: str,
    measurement: str,
    window: str = "PT24H",
    aggregation: Literal["mean", "max", "min", "last"] = "mean",
) -> str:
    """Read-only timeseries query against public.measurements.

    Args:
        device_id: Device identifier as published in measurements.device_id.
        measurement: Measurement name (e.g. state_of_charge, active_power).
        window: ISO-8601 duration ("PT24H") or shorthand ("24h","7d").
        aggregation: mean | max | min | last (hourly bucket).
    """
    td = _parse_window(window)
    client = ctx.deps.timeseries
    assert isinstance(client, TimeseriesClient)
    art = await build_timeseries(
        client, ctx.deps.site_id, device_id, measurement, td, aggregation
    )
    ctx.deps.artifacts.append(art)
    if art.kind == "error":
        return f"No {measurement} data for {device_id} over {window}."
    return f"Queried {measurement} on {device_id}, window={window}, agg={aggregation}."


async def describe_site(ctx: RunContext[_TelemetryDeps]) -> str:
    """Discover what's actually in the historian — call BEFORE query_timeseries.

    Returns the (device, measurement) registry as a TableSpec so the LLM
    knows which device_ids and measurement names to pass to other tools.
    Avoids the failure mode where the model guesses 'soc' but the data
    publishes as 'state_of_charge'.
    """
    client = ctx.deps.timeseries
    assert isinstance(client, TimeseriesClient)
    art = await build_site_description(client, ctx.deps.site_id)
    ctx.deps.artifacts.append(art)
    return f"Returned device+measurement registry for site '{ctx.deps.site_id}'."


async def list_devices_where(
    ctx: RunContext[_TelemetryDeps],
    status: list[str] | None = None,
) -> str:
    """List devices at the site, optionally filtered by latest status."""
    client = ctx.deps.timeseries
    assert isinstance(client, TimeseriesClient)
    art = await build_device_list(client, ctx.deps.site_id, status=status)
    ctx.deps.artifacts.append(art)
    return f"Listed devices status={','.join(status) if status else 'any'}."


async def query_markets(
    ctx: RunContext[_TelemetryDeps],
    window: str = "today",
    group_by: Literal["market", "hour"] = "market",
) -> str:
    """PLACEHOLDER - site revenue by market.

    Renders a labeled placeholder chart. Real implementation needs the
    revenue derivation pipeline (site dispatch x clearing price). See
    build_markets_stub docstring.
    """
    ctx.deps.artifacts.append(build_markets_stub(window, group_by))
    return (
        f"Returned PLACEHOLDER revenue chart (window={window}). "
        "Real revenue derivation pipeline is not yet wired."
    )


async def query_energy_breakdown(
    ctx: RunContext[_TelemetryDeps],
    window: str = "today",
    by: Literal["source", "destination"] = "source",
) -> str:
    """PLACEHOLDER - site energy mix breakdown.

    Renders a labeled placeholder chart. Real implementation needs the
    per-source meter measurement registry. See build_energy_breakdown_stub
    docstring.
    """
    ctx.deps.artifacts.append(build_energy_breakdown_stub(window, by))
    return (
        f"Returned PLACEHOLDER energy breakdown (window={window}, by={by}). "
        "Per-source meter measurement registry is not yet wired."
    )
