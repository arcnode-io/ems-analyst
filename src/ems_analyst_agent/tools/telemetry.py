"""Telemetry builders — Pydantic artifact factories backed by ServerClient.

Real builders (`build_timeseries`, `build_device_list`,
`build_site_description`) read through ems-analyst-server's REST API.
Stub builders (`build_markets_stub`, `build_energy_breakdown_stub`)
return clearly-labeled placeholder charts — the derivation pipelines
those features need don't exist yet.

RunContext wrappers live in `telemetry_tools.py`.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from ..schemas import (
    AnalystArtifact,
    BarSpec,
    LineSpec,
    PieSpec,
    TableSpec,
)
from ..server_client import Aggregation, ServerClient

_STUB_NOTE: str = " - PLACEHOLDER (derivation pipeline not yet wired)"


@dataclass
class _TelemetryDeps:
    """Structural deps shape — anything carrying these fields works."""

    artifacts: list[AnalystArtifact] = field(default_factory=list)
    site_id: str = ""
    server: object | None = None


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_window(window: str) -> timedelta:
    """Parse ISO-8601 duration (PT24H) or shorthand (24h, 7d) -> timedelta."""
    s = window.strip().lower()
    iso = re.match(r"^pt(\d+)([hm])$", s)
    if iso:
        n, unit = int(iso.group(1)), iso.group(2)
        return timedelta(hours=n) if unit == "h" else timedelta(minutes=n)
    short = re.match(r"^(\d+)([hdm])$", s)
    if short:
        n, unit = int(short.group(1)), short.group(2)
        if unit == "h":
            return timedelta(hours=n)
        if unit == "d":
            return timedelta(days=n)
        return timedelta(minutes=n)
    return timedelta(hours=24)


def _error_artifact(code: str, message: str) -> AnalystArtifact:
    return AnalystArtifact.model_validate(
        {
            "kind": "error",
            "spec": {"code": code, "message": message, "dataAsOf": _now()},
        }
    )


async def build_timeseries(
    client: ServerClient,
    site_id: str,
    device_id: str,
    measurement: str,
    window: timedelta,
    aggregation: Aggregation,
) -> AnalystArtifact:
    """Bucketed timeseries via server's /measurements; empty → error artifact."""
    end = datetime.now(UTC)
    start = end - window
    series = await client.get_measurements(
        site_id=site_id,
        device_id=device_id,
        measurement=measurement,
        start=start,
        end=end,
        aggregation=aggregation,
    )
    # All-None means the entire window is gap-filled → no data.
    has_real = any(p.value is not None for p in series.points)
    if not series.points or not has_real:
        return _error_artifact(
            "not_found",
            f"No {measurement} data for {device_id} over the last {window}.",
        )
    points = [
        {"x": p.ts.isoformat().replace("+00:00", "Z"), "y": p.value}
        for p in series.points
    ]
    spec = LineSpec.model_validate(
        {
            "title": f"{device_id} {measurement} ({aggregation}, last {window})",
            "xAxis": {"label": "Time", "kind": "time"},
            "yAxis": {"label": measurement, "unit": series.unit},
            "series": [{"label": device_id, "points": points}],
            "dataAsOf": _now(),
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "line", "spec": spec.model_dump(by_alias=True)}
    )


async def build_site_description(
    client: ServerClient,
    site_id: str,
) -> AnalystArtifact:
    """Distinct (device, measurement) pairs at the site — registry as a table."""
    desc = await client.describe_site(site_id=site_id)
    if not desc.pairs:
        return _error_artifact(
            "not_found", f"No measurements published for site '{site_id}' yet."
        )
    rows: list[dict[str, str | int]] = [
        {
            "device": p.device_id,
            "measurement": p.measurement,
            "samples": p.samples,
        }
        for p in desc.pairs
    ]
    spec = TableSpec.model_validate(
        {
            "title": f"Available data at site '{site_id}'",
            "columns": [
                {"key": "device", "label": "Device"},
                {"key": "measurement", "label": "Measurement"},
                {"key": "samples", "label": "Samples", "align": "right"},
            ],
            "rows": rows,
            "dataAsOf": _now(),
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "table", "spec": spec.model_dump(by_alias=True)}
    )


async def build_device_list(
    client: ServerClient,
    site_id: str,
    status: list[str] | None = None,
) -> AnalystArtifact:
    """Distinct device_ids at the site with their latest status."""
    devs = await client.list_devices(site_id=site_id, status=status)
    rows: list[dict[str, str | None]] = [
        {"device": d.device_id, "status": d.status} for d in devs.devices
    ]
    spec = TableSpec.model_validate(
        {
            "title": (
                f"Devices at site (status={','.join(status) if status else 'any'})"
            ),
            "columns": [
                {"key": "device", "label": "Device"},
                {"key": "status", "label": "Status"},
            ],
            "rows": rows,
            "rowSeverity": [
                d.status if d.status in ("ok", "warn", "alarm") else None
                for d in devs.devices
            ],
            "dataAsOf": _now(),
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "table", "spec": spec.model_dump(by_alias=True)}
    )


def build_markets_stub(
    window: str = "today",
    group_by: Literal["market", "hour"] = "market",
) -> AnalystArtifact:
    """STUB. Site revenue by market = sum(site_dispatch * clearing_price).

    Requires: site dispatch published per market product per interval +
    market clearing price feed (gridstatus.io has it) + revenue
    derivation service. Returns labeled placeholder so the chart renders
    and the LLM conveys uncertainty rather than presenting fake values
    as fact.
    """
    spec = BarSpec.model_validate(
        {
            "title": f"Revenue by {group_by} ({window}){_STUB_NOTE}",
            "xAxis": {"label": "Market", "categories": ["DAM", "RTM", "FREQ"]},
            "yAxis": {"label": "Revenue", "unit": "USD"},
            "series": [{"label": "placeholder", "values": [0.0, 0.0, 0.0]}],
            "dataAsOf": _now(),
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "bar", "spec": spec.model_dump(by_alias=True)}
    )


def build_energy_breakdown_stub(
    window: str = "today",
    by: Literal["source", "destination"] = "source",
) -> AnalystArtifact:
    """STUB. Per-source energy = integrate(source_power_kw dt) over window.

    Requires: per-source meter measurements named in a registry (e.g.
    solar_inverter_p_kw, grid_meter_p_kw) + trapezoidal integration over
    interval. Returns labeled placeholder so the chart renders and the
    LLM conveys uncertainty rather than presenting fake values as fact.
    """
    spec = PieSpec.model_validate(
        {
            "title": f"Energy by {by} ({window}){_STUB_NOTE}",
            "unit": "MWh",
            "slices": [{"label": "placeholder", "value": 0.0}],
            "dataAsOf": _now(),
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "pie", "spec": spec.model_dump(by_alias=True)}
    )
