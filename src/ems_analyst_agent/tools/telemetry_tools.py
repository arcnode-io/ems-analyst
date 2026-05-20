"""RunContext wrappers around telemetry + site-analytics builders.

Separated from telemetry.py to keep each file under the 200-line cap.
The Agent imports these and registers them as Tool() instances.
"""

from typing import Literal

from pydantic_ai import RunContext

from ..device_api import DeviceApiClient
from ..server_client import ServerClient
from .site_analytics import build_energy_breakdown, build_markets
from .telemetry import _TelemetryDeps, _parse_window, build_timeseries


async def query_timeseries(
    ctx: RunContext[_TelemetryDeps],
    device_id: str,
    measurement: str,
    window: str = "PT24H",
    aggregation: Literal["mean", "max", "min", "last"] = "mean",
) -> str:
    """Read-only timeseries query through ems-analyst-server.

    Args:
        device_id: Device identifier as published in measurements.device_id.
        measurement: Measurement name (e.g. state_of_charge, active_power).
        window: ISO-8601 duration ("PT24H") or shorthand ("24h","7d").
        aggregation: mean | max | min | last (hourly bucket).
    """
    td = _parse_window(window)
    client = ctx.deps.server
    assert isinstance(client, ServerClient)
    art = await build_timeseries(client, device_id, measurement, td, aggregation)
    ctx.deps.artifacts.append(art)
    if art.kind == "error":
        return f"No {measurement} data for {device_id} over {window}."
    return f"Queried {measurement} on {device_id}, window={window}, agg={aggregation}."


async def query_markets(
    ctx: RunContext[_TelemetryDeps],
    window: str = "24h",
) -> str:
    """Site revenue by market (DAM + RTM) over the window.

    Revenue = Σ_hour( dispatch_mw * clearing_price_$/MWh ). BarSpec
    with one bar per market.

    Args:
        window: ISO-8601 duration ("PT24H") or shorthand ("24h","7d","30d").
    """
    td = _parse_window(window)
    client = ctx.deps.server
    device_api = ctx.deps.device_api
    assert isinstance(client, ServerClient)
    assert isinstance(device_api, DeviceApiClient)
    dtm = await device_api.get_topology()
    art = await build_markets(client, dtm, td)
    ctx.deps.artifacts.append(art)
    if art.kind == "error":
        return f"No market dispatch data over {window}."
    return f"Returned revenue by market for the last {window}."


async def query_energy_breakdown(
    ctx: RunContext[_TelemetryDeps],
    window: str = "24h",
    by: Literal["source", "destination"] = "source",
) -> str:
    """Site energy mix by source or destination over the window.

    Source = BESS discharge + grid import. Destination = compute load +
    BESS charge + grid export. Integrated per-device power → kWh,
    rendered as PieSpec.

    Args:
        window: ISO-8601 duration ("PT24H") or shorthand ("24h","7d").
        by: source | destination — direction of energy flow.
    """
    td = _parse_window(window)
    client = ctx.deps.server
    device_api = ctx.deps.device_api
    assert isinstance(client, ServerClient)
    assert isinstance(device_api, DeviceApiClient)
    dtm = await device_api.get_topology()
    art = await build_energy_breakdown(client, dtm, td, by)
    ctx.deps.artifacts.append(art)
    if art.kind == "error":
        return f"No energy {by} data over {window}."
    return f"Returned energy by {by} for the last {window}."
