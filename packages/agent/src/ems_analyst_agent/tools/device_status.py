"""Device-status artifact builder — one table across every gradeable device.

Split out of telemetry.py once this grew its own multi-source rollup
(literal `status` measurement + device_health.py's per-family derivation)
— see device_health.py for the severity rules themselves.
"""

from ..isotime import iso_z
from ..schemas import AnalystArtifact, RowSeverity, TableSpec
from ..server_client import ServerClient
from ._common import _error_artifact
from .device_health import FAMILY_RULES, RawValues, device_family

_STATUS_MEASUREMENT: str = "status"
# Devices named by the summary note before it collapses to "+N more" — keeps
# the one line the LLM reads (see _status_note) readable even when dozens of
# devices in a real fleet share the same non-ok status.
_NOTE_MAX_NAMED: int = 5


def _severity(state: str) -> RowSeverity | None:
    """Map a status value to a table row severity, or None if unrecognized.

    Case-insensitive — real telemetry publishes "OK" uppercase for at
    least one device (operating_envelope), the CSV-era convention was
    lowercase; both should resolve the same way.
    """
    match state.lower():
        case "ok":
            return "ok"
        case "warn":
            return "warn"
        case "alarm":
            return "alarm"
        case _:
            return None


async def build_device_status(client: ServerClient) -> AnalystArtifact:
    """Current health for every device with a derivable signal — one table.

    Two sources, by priority, per device:
    1. A device publishing the literal `status` enum uses it directly
       (ok/warn/alarm text) — the original convention.
    2. Otherwise, if the device's family (its device_id minus a trailing
       `_<N>` instance suffix — see device_health.device_family) has a
       known derivation rule, its required raw signals are fetched and
       combined into a severity + display string (device_health.py).
    A device matching neither is omitted, same as today.

    All reads go through get_latest_measurements(): one bulk call for
    every `status` device, plus one more per matched family — a small
    constant regardless of fleet size, not one call per device. A real
    device fleet runs into the hundreds; an N-round-trips loop isn't
    viable for an interactive chat response.
    """
    desc = await client.describe_site()
    status_ids = sorted(
        {p.device_id for p in desc.pairs if p.measurement == _STATUS_MEASUREMENT}
    )
    by_family: dict[str, list[str]] = {}
    for device_id in {p.device_id for p in desc.pairs} - set(status_ids):
        family = device_family(device_id)
        if family in FAMILY_RULES:
            by_family.setdefault(family, []).append(device_id)

    rows: list[dict[str, str]] = []
    severities: list[RowSeverity | None] = []

    if status_ids:
        latest = await client.get_latest_measurements(
            device_ids=status_ids, measurements=[_STATUS_MEASUREMENT]
        )
        values = {v.device_id: v.value for v in latest.values}
        for device_id in status_ids:
            raw = values.get(device_id)
            state = str(raw) if raw is not None else "unknown"
            rows.append({"device": device_id, "status": state})
            severities.append(_severity(state))

    for family in sorted(by_family):
        device_ids = sorted(by_family[family])
        rule = FAMILY_RULES[family]
        latest = await client.get_latest_measurements(
            device_ids=device_ids, measurements=rule.measurements
        )
        values: dict[str, RawValues] = {}
        for v in latest.values:
            values.setdefault(v.device_id, {})[v.measurement] = v.value
        for device_id in device_ids:
            severity, display = rule.derive(values.get(device_id, {}))
            rows.append({"device": device_id, "status": display})
            severities.append(severity)

    if not rows:
        return _error_artifact("not_found", "No status-reporting devices at this site.")
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
            "note": _status_note(rows, severities),
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "table", "spec": spec.model_dump(by_alias=True)}
    )


def _status_note(
    rows: list[dict[str, str]], severities: list[RowSeverity | None]
) -> str:
    """One-line severity summary, naming devices that aren't ok.

    e.g. '1 alarm (cdu_01), 1 warn (bess_module_02), 3 ok' — this is the
    only thing the LLM reads back (it never sees the table's rows), so
    non-ok devices need to be named here or it has to go fishing with
    other tools to find out which device is the problem. Grouped by
    severity, not by display text — family-derived rows show things like
    "tripped" or "SW_POWER_CAP" rather than the literal word "alarm"/
    "warn". Device names are capped per group (_NOTE_MAX_NAMED) so a real
    fleet where dozens of devices share one status doesn't blow up this
    line — it collapses to "+N more" instead.
    """
    devices_by_severity: dict[str, list[str]] = {}
    for row, severity in zip(rows, severities, strict=True):
        devices_by_severity.setdefault(severity or "unknown", []).append(row["device"])
    ordered = [
        s for s in ("alarm", "warn", "ok", "unknown") if s in devices_by_severity
    ]
    parts = []
    for severity in ordered:
        devices = devices_by_severity[severity]
        if severity == "ok":
            parts.append(f"{len(devices)} {severity}")
            continue
        named = devices[:_NOTE_MAX_NAMED]
        overflow = len(devices) - len(named)
        label = ", ".join(named) + (f", +{overflow} more" if overflow else "")
        parts.append(f"{len(devices)} {severity} ({label})")
    return ", ".join(parts)
