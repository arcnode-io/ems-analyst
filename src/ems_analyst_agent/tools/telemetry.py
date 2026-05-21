"""Telemetry builders — Pydantic artifact factories backed by ServerClient.

`build_timeseries` reads through ems-analyst-server's REST API. Markets
revenue + energy breakdown live in `site_analytics.py`. RunContext
wrappers in `telemetry_tools.py`.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ..schemas import AnalystArtifact, LineSpec
from ..server_client import Aggregation, ServerClient


@dataclass
class _TelemetryDeps:
    """Structural deps shape — anything carrying these fields works.

    No site_id: each deploy serves one site; the server resolves it
    from cfg. Tools just hit the flat endpoints.
    """

    artifacts: list[AnalystArtifact] = field(default_factory=list)
    server: object | None = None
    device_api: object | None = None


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


def _fmt_window(td: timedelta) -> str:
    """Human window label — '7d' / '24h' / '30m'. Avoids raw timedelta repr."""
    secs = int(td.total_seconds())
    if secs and secs % 86400 == 0:
        return f"{secs // 86400}d"
    if secs and secs % 3600 == 0:
        return f"{secs // 3600}h"
    return f"{secs // 60}m"


def _error_artifact(code: str, message: str) -> AnalystArtifact:
    return AnalystArtifact.model_validate(
        {
            "kind": "error",
            "spec": {"code": code, "message": message, "dataAsOf": _now()},
        }
    )


async def build_timeseries(
    client: ServerClient,
    device_id: str,
    measurement: str,
    window: timedelta,
    aggregation: Aggregation,
) -> AnalystArtifact:
    """Bucketed timeseries via server's /measurements; empty → error artifact."""
    end = datetime.now(UTC)
    start = end - window
    series = await client.get_measurements(
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
            f"No {measurement} data for {device_id} over the last "
            f"{_fmt_window(window)}.",
        )
    points = [
        {"x": p.ts.isoformat().replace("+00:00", "Z"), "y": p.value}
        for p in series.points
    ]
    spec = LineSpec.model_validate(
        {
            "title": (
                f"{device_id} {measurement} "
                f"({aggregation}, last {_fmt_window(window)})"
            ),
            "xAxis": {"label": "Time", "kind": "time"},
            "yAxis": {"label": measurement, "unit": series.unit},
            "series": [{"label": device_id, "points": points}],
            "dataAsOf": _now(),
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "line", "spec": spec.model_dump(by_alias=True)}
    )
