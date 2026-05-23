"""Shared building blocks for the telemetry / analytics tool modules.

The structural deps shape, window parsing/labelling, the error-artifact
helper, and the chart→table re-render — kept in one place so
`telemetry`, `site_analytics`, `forecast` and `topology_tool` lean on it
without importing one another.
"""

import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

from ..isotime import iso_z
from ..schemas import AnalystArtifact, BarSpec, LineSpec, PieSpec, TableSpec

Render = Literal["chart", "table"]


@dataclass
class _TelemetryDeps:
    """Structural deps a RunContext tool reads.

    `artifacts` is the sink every builder appends to; the HTTP layer
    assembles the reply from it. `server` / `device_api` are the REST
    clients (typed `object` so tools stay decoupled from the concrete
    client classes).
    """

    artifacts: list[AnalystArtifact] = field(default_factory=list)
    server: object | None = None
    device_api: object | None = None


def _parse_window(window: str) -> timedelta:
    """Parse an ISO-8601 duration (PT24H) or shorthand (24h, 7d) -> timedelta."""
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


def _fmt_window(td: timedelta) -> str:
    """Human window label — '7d' / '24h' / '30m'. Avoids raw timedelta repr."""
    secs = int(td.total_seconds())
    if secs and secs % 86400 == 0:
        return f"{secs // 86400}d"
    if secs and secs % 3600 == 0:
        return f"{secs // 3600}h"
    return f"{secs // 60}m"


def _error_artifact(code: str, message: str) -> AnalystArtifact:
    """Build an `error`-kind AnalystArtifact for a failed tool call."""
    return AnalystArtifact.model_validate(
        {
            "kind": "error",
            "spec": {"code": code, "message": message, "dataAsOf": iso_z()},
        }
    )


def _to_table(artifact: AnalystArtifact) -> AnalystArtifact:
    """Re-render a chart artifact's data as a TableSpec artifact.

    Backs the `render="table"` tool option — same data, table card
    instead of a chart. Error artifacts pass through unchanged; tables
    are returned as-is.
    """
    spec = artifact.spec
    columns: list[dict[str, str]]
    rows: list[dict[str, str | float | None]]
    if isinstance(spec, LineSpec):
        series = spec.series[0]
        columns = [
            {"key": "time", "label": spec.x_axis.label},
            {"key": "value", "label": spec.y_axis.label},
        ]
        rows = [{"time": str(p.x), "value": p.y} for p in series.points]
    elif isinstance(spec, BarSpec):
        series = spec.series[0]
        columns = [
            {"key": "category", "label": spec.x_axis.label},
            {"key": "value", "label": series.label},
        ]
        rows = [
            {"category": c, "value": v}
            for c, v in zip(spec.x_axis.categories, series.values, strict=True)
        ]
    elif isinstance(spec, PieSpec):
        columns = [
            {"key": "label", "label": "Category"},
            {"key": "value", "label": spec.unit},
        ]
        rows = [{"label": s.label, "value": s.value} for s in spec.slices]
    else:
        # error or already a table — nothing to re-render
        return artifact
    table = TableSpec.model_validate(
        {
            "title": spec.title,
            "columns": columns,
            "rows": rows,
            "dataAsOf": spec.data_as_of,
            "note": spec.note,
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "table", "spec": table.model_dump(by_alias=True)}
    )
