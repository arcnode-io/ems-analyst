"""RunContext wrappers around telemetry + site-analytics builders.

Separated from telemetry.py to keep each file under the 200-line cap.
The Agent imports these and registers them as Tool() instances.
"""

from typing import Literal

from pydantic_ai import RunContext

from ..device_api import DeviceApiClient
from ..schemas import TableSpec
from ..server_client import ServerClient
from ._common import Render, _TelemetryDeps, _parse_window, _to_table
from .dispatch_explain_artifact import build_explain_dispatch
from .site_analytics import build_energy_breakdown, build_markets
from .telemetry import build_device_status, build_site_description, build_timeseries


async def query_timeseries(
    ctx: RunContext[_TelemetryDeps],
    device_id: str,
    measurement: str,
    window: str = "PT24H",
    aggregation: Literal["mean", "max", "min", "last"] = "mean",
    render: Render = "chart",
) -> str:
    """Read-only timeseries query through ems-analyst-server.

    Args:
        device_id: Device identifier as published in measurements.device_id.
        measurement: Measurement name (e.g. state_of_charge, active_power).
        window: ISO-8601 duration ("PT24H") or shorthand ("24h","7d").
        aggregation: mean | max | min | last (hourly bucket).
        render: "chart" for a line chart, "table" for a data table.
    """
    td = _parse_window(window)
    client = ctx.deps.server
    assert isinstance(client, ServerClient)
    art = await build_timeseries(client, device_id, measurement, td, aggregation)
    if render == "table":
        art = _to_table(art)
    ctx.deps.artifacts.append(art)
    if art.kind == "error":
        return f"No {measurement} data for {device_id} over {window}."
    return f"Queried {measurement} on {device_id} ({render}, window={window})."


async def describe_site(ctx: RunContext[_TelemetryDeps]) -> str:
    """Discover what's queryable — call this BEFORE query_timeseries.

    Returns the (device, measurement) inventory as a table: the exact
    historian names + sample counts. Use the names it returns verbatim.
    Catches the failure mode where the model guesses 'lmp' or
    'clearing_price' but the data publishes as
    'dam_clearing_price_usd_per_mwh'. Covers non-device series (e.g.
    market price feeds) that get_topology won't show.
    """
    # Code-enforced once-per-turn: system.md says "at most once" but the
    # model routinely ignored it, burning tool-call budget on repeats.
    if ctx.deps.site_description_cache is not None:
        ctx.deps.artifacts.append(ctx.deps.site_description_cache)
        return "(already have the site inventory from earlier this turn)"
    client = ctx.deps.server
    assert isinstance(client, ServerClient)
    art = await build_site_description(client)
    ctx.deps.site_description_cache = art
    ctx.deps.artifacts.append(art)
    return "Returned the queryable device+measurement inventory."


async def get_device_status(ctx: RunContext[_TelemetryDeps]) -> str:
    """Current status/alarm state for every status-reporting device — one table.

    Prefer this over calling query_timeseries('status') per device — it's
    one tool call instead of N, and answers "which devices are in alarm"
    directly.
    """
    client = ctx.deps.server
    assert isinstance(client, ServerClient)
    art = await build_device_status(client)
    ctx.deps.artifacts.append(art)
    if art.kind == "error":
        return "No status-reporting devices at this site."
    # The LLM never sees the table's rows, only this return string — a
    # vague "returned the data" here gives it nothing to answer from and
    # it'll guess (observed: claimed "no alarms" while the table showed
    # one). Surface the real severity counts so it has something true.
    assert isinstance(art.spec, TableSpec)
    return f"Device status: {art.spec.note}."


async def explain_dispatch(
    ctx: RunContext[_TelemetryDeps],
    device_id: str,
    window: str = "24h",
) -> str:
    """Why did a BESS device charge/discharge — price vs. dispatch, deterministic.

    For "why did the battery charge/discharge" questions, call this
    instead of reconstructing it from query_timeseries — it correlates
    the DAM price against dispatch and returns the actual numbers
    (median/peak price, hours, revenue, spread, SoC swing) below. No LLM
    in the math.

    Args:
        device_id: A BESS device (e.g. bess_module_01).
        window: ISO-8601 duration ("PT24H") or shorthand ("24h","7d").
    """
    td = _parse_window(window)
    client = ctx.deps.server
    assert isinstance(client, ServerClient)
    artifacts, stats = await build_explain_dispatch(client, device_id, td)
    ctx.deps.artifacts.extend(artifacts)
    if stats is None:
        return f"No price data for {device_id} over {window}."
    peak = (
        f"{stats.peak_start:%H:%M}-{stats.peak_end:%H:%M}"
        if stats.peak_start and stats.peak_end
        else "no clear peak"
    )
    action = "discharged" if stats.peak_dispatch_confirmed else "did not discharge"
    spread = f"${stats.spread:.0f}/MWh" if stats.spread is not None else "n/a"
    soc = (
        f"{stats.soc_min:.0f}%->{stats.soc_max:.0f}%"
        if stats.soc_min is not None and stats.soc_max is not None
        else "n/a"
    )
    return (
        f"{device_id} {action} across the {peak} peak "
        f"(avg ${stats.peak_avg_price or 0:.0f} vs ${stats.median_price:.0f} median). "
        f"Dispatch: {stats.discharge_hours}h discharge, {stats.charge_hours}h charge. "
        f"SoC {soc}. Revenue ${stats.net_revenue:,.0f} "
        f"(discharge ${stats.discharge_revenue:,.0f}, "
        f"charge cost ${stats.charge_cost:,.0f}); spread {spread}."
    )


async def query_markets(
    ctx: RunContext[_TelemetryDeps],
    window: str = "24h",
    render: Render = "chart",
) -> str:
    """Site revenue by market (DAM + RTM) over the window.

    Revenue = Σ_hour( dispatch_mw * clearing_price_$/MWh ).

    Args:
        window: ISO-8601 duration ("PT24H") or shorthand ("24h","7d","30d").
        render: "chart" for a bar chart, "table" for a data table.
    """
    td = _parse_window(window)
    client = ctx.deps.server
    device_api = ctx.deps.device_api
    assert isinstance(client, ServerClient)
    assert isinstance(device_api, DeviceApiClient)
    dtm = await device_api.get_topology()
    art = await build_markets(client, dtm, td)
    if render == "table":
        art = _to_table(art)
    ctx.deps.artifacts.append(art)
    if art.kind == "error":
        return f"No market dispatch data over {window}."
    return f"Returned revenue by market ({render}) for the last {window}."


async def query_energy_breakdown(
    ctx: RunContext[_TelemetryDeps],
    window: str = "24h",
    by: Literal["source", "destination"] = "source",
    render: Render = "chart",
) -> str:
    """Site energy mix by source or destination over the window.

    Source = BESS discharge + grid import. Destination = compute load +
    BESS charge + grid export. Integrated per-device power → kWh.

    Args:
        window: ISO-8601 duration ("PT24H") or shorthand ("24h","7d").
        by: source | destination — direction of energy flow.
        render: "chart" for a pie chart, "table" for a data table.
    """
    td = _parse_window(window)
    client = ctx.deps.server
    device_api = ctx.deps.device_api
    assert isinstance(client, ServerClient)
    assert isinstance(device_api, DeviceApiClient)
    dtm = await device_api.get_topology()
    art = await build_energy_breakdown(client, dtm, td, by)
    if render == "table":
        art = _to_table(art)
    ctx.deps.artifacts.append(art)
    if art.kind == "error":
        return f"No energy {by} data over {window}."
    return f"Returned energy by {by} ({render}) for the last {window}."
