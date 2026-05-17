"""Stub telemetry tools that return render-spec artifacts.

Synthetic data only — TODO: replace each stub with TimescaleDB historian
+ device-registry queries once the EMS data layer lands.

Structure:
- builders (`build_*`) — pure functions returning AnalystArtifact;
  unit-tested directly.
- tools (`query_*`, `list_*`) — thin RunContext-aware wrappers that
  call the builder, append to ctx.deps.artifacts, and return prose for
  the LLM. Registered on the Agent.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pydantic_ai import RunContext

from ..schemas import (
    AnalystArtifact,
    BarSpec,
    LineSpec,
    PieSpec,
    TableSpec,
)

# Synthetic device registry — replace with real device-registry query.
_KNOWN_DEVICES: frozenset[str] = frozenset(
    {"BESS-01", "BESS-02", "BESS-03", "COMPUTE-POD-1", "GRID-METER-1"}
)


@dataclass
class _ArtifactSink:
    """Anything with an `artifacts: list[AnalystArtifact]` field works as deps."""

    artifacts: list[AnalystArtifact] = field(default_factory=list)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _error_artifact(code: str, message: str) -> AnalystArtifact:
    return AnalystArtifact.model_validate(
        {
            "kind": "error",
            "spec": {"code": code, "message": message, "dataAsOf": _now()},
        }
    )


# ── builders (pure) ────────────────────────────────────────────────────────


def build_timeseries(
    device_id: str,
    measurement: str,
    window: str = "PT24H",
    aggregation: Literal["mean", "max", "min", "last"] = "mean",
) -> AnalystArtifact:
    """Build a LineSpec artifact for device.measurement over window (STUB)."""
    if device_id not in _KNOWN_DEVICES:
        return _error_artifact(
            "not_found", f"Device '{device_id}' not found in registry."
        )
    # TODO: replace with historian.query(device_id, measurement, window, ...)
    points = [
        {"x": f"2026-05-16T{hr:02d}:00:00Z", "y": 80.0 - hr * 1.5}
        for hr in range(0, 24)
    ]
    spec = LineSpec.model_validate(
        {
            "title": f"{device_id} {measurement} ({window}, {aggregation})",
            "xAxis": {"label": "Time", "kind": "time"},
            "yAxis": {"label": measurement, "unit": "%"},
            "series": [{"label": device_id, "points": points}],
            "dataAsOf": _now(),
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "line", "spec": spec.model_dump(by_alias=True)}
    )


def build_device_list(
    status: list[str] | None = None,
    template: str | None = None,
) -> AnalystArtifact:
    """Build a TableSpec artifact for devices matching status filter (STUB)."""
    # TODO: replace with device_registry.query(template, status, measurement_filter)
    rows: list[dict[str, str | float | None]] = [
        {"device": "BESS-01", "template": "bess_rack", "status": "alarm", "soc": 12.3},
        {"device": "BESS-02", "template": "bess_rack", "status": "ok", "soc": 78.1},
        {"device": "BESS-03", "template": "bess_rack", "status": "warn", "soc": 22.0},
    ]
    if status:
        rows = [r for r in rows if r["status"] in status]
    if template:
        rows = [r for r in rows if r["template"] == template]
    spec = TableSpec.model_validate(
        {
            "title": (
                f"Device list ({template or 'any'} / "
                f"{','.join(status) if status else 'any'})"
            ),
            "columns": [
                {"key": "device", "label": "Device"},
                {"key": "template", "label": "Template"},
                {"key": "status", "label": "Status"},
                {"key": "soc", "label": "SoC", "align": "right", "unit": "%"},
            ],
            "rows": rows,
            "rowSeverity": [
                r["status"] if r["status"] in ("ok", "warn", "alarm") else None
                for r in rows
            ],
            "dataAsOf": _now(),
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "table", "spec": spec.model_dump(by_alias=True)}
    )


def build_markets(
    window: str = "today",
    group_by: Literal["market", "hour"] = "market",
) -> AnalystArtifact:
    """Build a BarSpec artifact for revenue by market (STUB)."""
    # TODO: replace with revenue_service.query(window, group_by)
    spec = BarSpec.model_validate(
        {
            "title": f"Revenue by {group_by} ({window})",
            "xAxis": {"label": "Market", "categories": ["DAM", "RTM", "FREQ"]},
            "yAxis": {"label": "Revenue", "unit": "USD"},
            "series": [{"label": "site_1", "values": [12340.5, 6789.1, 2341.7]}],
            "dataAsOf": _now(),
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "bar", "spec": spec.model_dump(by_alias=True)}
    )


def build_energy_breakdown(
    window: str = "today",
    by: Literal["source", "destination"] = "source",
) -> AnalystArtifact:
    """Build a PieSpec artifact for energy mix breakdown (STUB)."""
    # TODO: replace with energy_service.breakdown(window, by)
    spec = PieSpec.model_validate(
        {
            "title": f"Energy by {by} ({window})",
            "unit": "MWh",
            "slices": [
                {"label": "solar", "value": 120.5},
                {"label": "wind", "value": 88.2},
                {"label": "grid_import", "value": 42.1},
            ],
            "dataAsOf": _now(),
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "pie", "spec": spec.model_dump(by_alias=True)}
    )


# ── tools (RunContext-aware wrappers) ──────────────────────────────────────


async def query_timeseries(
    ctx: RunContext[_ArtifactSink],
    device_id: str,
    measurement: str,
    window: str = "PT24H",
    aggregation: Literal["mean", "max", "min", "last"] = "mean",
) -> str:
    """Read-only timeseries query against the EMS historian (STUB).

    Args:
        device_id: Device identifier from the registry (e.g. BESS-01).
        measurement: Measurement name (e.g. state_of_charge, net_power_kw).
        window: ISO-8601 duration ("PT24H") or named ("1h","24h","7d").
        aggregation: mean | max | min | last.
    """
    art = build_timeseries(device_id, measurement, window, aggregation)
    ctx.deps.artifacts.append(art)
    if art.kind == "error":
        return f"Device '{device_id}' not found."
    return (
        f"Queried 24 points of {measurement} on {device_id} "
        f"over window={window} agg={aggregation}."
    )


async def list_devices_where(
    ctx: RunContext[_ArtifactSink],
    template: str | None = None,
    status: list[str] | None = None,
) -> str:
    """Read-only device list filtered by template / status (STUB)."""
    art = build_device_list(status=status, template=template)
    ctx.deps.artifacts.append(art)
    status_str = ",".join(status) if status else "any"
    return f"Listed devices with template={template or 'any'}, status={status_str}."


async def query_markets(
    ctx: RunContext[_ArtifactSink],
    window: str = "today",
    group_by: Literal["market", "hour"] = "market",
) -> str:
    """Read-only revenue-by-market query (STUB)."""
    art = build_markets(window=window, group_by=group_by)
    ctx.deps.artifacts.append(art)
    return f"Computed market revenue for window={window}, group_by={group_by}."


async def query_energy_breakdown(
    ctx: RunContext[_ArtifactSink],
    window: str = "today",
    by: Literal["source", "destination"] = "source",
) -> str:
    """Read-only energy-mix breakdown (STUB)."""
    art = build_energy_breakdown(window, by)
    ctx.deps.artifacts.append(art)
    return f"Computed energy breakdown for window={window} by {by}."
