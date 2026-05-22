"""Shared building blocks for the telemetry / analytics tool modules.

The structural deps shape, window parsing/labelling, and the
error-artifact helper — kept in one place so `telemetry`,
`site_analytics`, `forecast` and `topology_tool` lean on it without
importing one another.
"""

import re
from dataclasses import dataclass, field
from datetime import timedelta

from ..isotime import iso_z
from ..schemas import AnalystArtifact


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
