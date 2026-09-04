"""Timeseries + site-inventory artifact builders, backed by ServerClient.

`build_timeseries` charts a historian series; `build_site_description`
tables the queryable-data inventory. Markets revenue + energy breakdown
live in `site_analytics.py`; RunContext wrappers in `telemetry_tools.py`.
"""

from datetime import UTC, datetime, timedelta

from ..isotime import iso_z
from ..schemas import AnalystArtifact, LineSpec, RowSeverity, TableSpec
from ..server_client import Aggregation, ServerClient
from ._common import _error_artifact, _fmt_window

_STATUS_MEASUREMENT: str = "status"
_STATUS_WINDOW: timedelta = timedelta(hours=24)


def _severity(state: str) -> RowSeverity | None:
    """Map a status value to a table row severity, or None if unrecognized."""
    match state:
        case "ok":
            return "ok"
        case "warn":
            return "warn"
        case "alarm":
            return "alarm"
        case _:
            return None


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
    ys = [p.value for p in series.points if p.value is not None]
    numeric_ys = [y for y in ys if isinstance(y, float)]
    if not ys:
        note = None
    elif len(numeric_ys) == len(ys):
        note = f"{min(numeric_ys):g}-{max(numeric_ys):g} {series.unit}, latest {numeric_ys[-1]:g}"
    else:
        note = f"latest {ys[-1]} {series.unit}".strip()
    spec = LineSpec.model_validate(
        {
            "title": (
                f"{device_id} {measurement} "
                f"({aggregation}, last {_fmt_window(window)})"
            ),
            "xAxis": {"label": "Time", "kind": "time"},
            "yAxis": {"label": measurement, "unit": series.unit},
            "series": [{"label": device_id, "points": points}],
            "dataAsOf": iso_z(),
            "note": note,
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "line", "spec": spec.model_dump(by_alias=True)}
    )


async def build_site_description(client: ServerClient) -> AnalystArtifact:
    """Queryable (device, measurement) pairs — the historian inventory.

    The discovery surface: what the agent can actually pull, with the
    exact names + sample counts. Includes non-device series (e.g. market
    price feeds) that the DTM has no device for.
    """
    desc = await client.describe_site()
    if not desc.pairs:
        return _error_artifact(
            "not_found", "No measurements published for this site yet."
        )
    rows: list[dict[str, str | int]] = [
        {"device": p.device_id, "measurement": p.measurement, "samples": p.samples}
        for p in desc.pairs
    ]
    devices = {p.device_id for p in desc.pairs}
    spec = TableSpec.model_validate(
        {
            "title": "Queryable measurements at this site",
            "columns": [
                {"key": "device", "label": "Device"},
                {"key": "measurement", "label": "Measurement"},
                {"key": "samples", "label": "Samples", "align": "right"},
            ],
            "rows": rows,
            "dataAsOf": iso_z(),
            "note": f"{len(rows)} series across {len(devices)} devices",
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "table", "spec": spec.model_dump(by_alias=True)}
    )


async def build_device_status(client: ServerClient) -> AnalystArtifact:
    """Current status for every device that publishes one — one table.

    One tool call instead of one query_timeseries('status') per device:
    describe_site tells us which devices have a status measurement, then
    each is queried for its latest value and folded into a single table.
    """
    desc = await client.describe_site()
    device_ids = [
        p.device_id for p in desc.pairs if p.measurement == _STATUS_MEASUREMENT
    ]
    if not device_ids:
        return _error_artifact("not_found", "No status-reporting devices at this site.")
    end = datetime.now(UTC)
    start = end - _STATUS_WINDOW
    rows: list[dict[str, str]] = []
    severities: list[RowSeverity | None] = []
    for device_id in device_ids:
        series = await client.get_measurements(
            device_id=device_id,
            measurement=_STATUS_MEASUREMENT,
            start=start,
            end=end,
            aggregation="last",
        )
        latest = next(
            (p.value for p in reversed(series.points) if p.value is not None), None
        )
        state = str(latest) if latest is not None else "unknown"
        rows.append({"device": device_id, "status": state})
        severities.append(_severity(state))
    spec = TableSpec.model_validate(
        {
            "title": "Device status",
            "columns": [
                {"key": "device", "label": "Device"},
                {"key": "status", "label": "Status"},
            ],
            "rows": rows,
            "rowSeverity": severities,
            "dataAsOf": iso_z(),
            "note": _status_note(rows),
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "table", "spec": spec.model_dump(by_alias=True)}
    )


def _status_note(rows: list[dict[str, str]]) -> str:
    """One-line severity summary, e.g. '1 alarm, 1 warn, 4 ok'."""
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    ordered = [s for s in ("alarm", "warn", "ok") if s in counts]
    ordered += [s for s in counts if s not in ordered]
    return ", ".join(f"{counts[s]} {s}" for s in ordered)
