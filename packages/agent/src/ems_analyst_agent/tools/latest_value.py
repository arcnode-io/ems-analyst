"""get_latest_value tool — current reading of one measurement across the fleet.

Built because "what's the fleet state of charge right now?" took 9 tool
calls and 90 s on the demo box: no tool answered "right now", so the model
explored topology + inventory + knowledge search and then queried devices
one at a time through hourly-bucketed timeseries. Tool time was ~8 s; the
other ~80 s was an LLM round trip after every call. One deterministic call
(inventory -> one bulk latest read -> numbers in the summary) replaces it.

The model never sees the table rows, only the summary string — so the real
numbers (and how stale they are) have to be in the summary.
"""

import re
from datetime import UTC, datetime

from pydantic_ai import RunContext

from ..isotime import iso_z
from ..schemas import AnalystArtifact, TableSpec
from ..server_client import LatestValue, ServerClient
from ._common import _error_artifact, _TelemetryDeps

# Devices listed individually in the summary before it collapses to "+N more".
_SUMMARY_MAX_DEVICES: int = 8


def _normalize(name: str) -> str:
    """'State of Charge' / 'state-of-charge' -> 'state_of_charge'."""
    return re.sub(r"[\s\-]+", "_", name.strip().lower())


def _resolve(query: str, available: set[str]) -> str | None:
    """Exact (normalized) match, else the single measurement containing the query."""
    q = _normalize(query)
    by_norm = {_normalize(m): m for m in available}
    if q in by_norm:
        return by_norm[q]
    partial = [m for n, m in by_norm.items() if q in n]
    return partial[0] if len(partial) == 1 else None


def _age(now: datetime, ts: datetime) -> str:
    """Human age of the newest reading — '12 min ago' / '3 h ago' / '2 d ago'."""
    minutes = max(int((now - ts).total_seconds() // 60), 0)
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 60 * 48:
        return f"{minutes // 60} h ago"
    return f"{minutes // (60 * 24)} d ago"


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _stats(values: list[LatestValue]) -> str:
    """avg/min/max (naming the devices) for numbers, else counts per value."""
    if all(_is_number(v.value) for v in values):
        nums = [(float(v.value), v.device_id) for v in values]  # ty: ignore[invalid-argument-type]
        lo, hi = min(nums), max(nums)
        avg = sum(n for n, _ in nums) / len(nums)
        return f"avg {avg:.1f}, min {lo[0]:.1f} ({lo[1]}), max {hi[0]:.1f} ({hi[1]})"
    counts: dict[str, int] = {}
    for v in values:
        key = "unknown" if v.value is None else str(v.value)
        counts[key] = counts.get(key, 0) + 1
    return ", ".join(f"{n} {k}" for k, n in counts.items())


def _per_device(values: list[LatestValue]) -> str:
    shown = [f"{v.device_id} {v.value}" for v in values[:_SUMMARY_MAX_DEVICES]]
    overflow = len(values) - len(shown)
    return "; ".join(shown) + (f"; +{overflow} more" if overflow else "")


async def build_latest_value(
    client: ServerClient, measurement: str, now: datetime | None = None
) -> tuple[AnalystArtifact, str]:
    """One table (device / value / updated) + the summary the LLM reads.

    `now` is exposed for tests — it only feeds the "N min ago" staleness text.
    """
    now = now or datetime.now(UTC)
    desc = await client.describe_site()
    available = {p.measurement for p in desc.pairs}
    resolved = _resolve(measurement, available)
    if resolved is None:
        q = _normalize(measurement)
        candidates = sorted(m for m in available if q in _normalize(m)) or sorted(
            available
        )
        msg = (
            f"No unique measurement matches {measurement!r}. "
            f"Available: {', '.join(candidates)}."
        )
        return _error_artifact("not_found", msg), msg

    device_ids = sorted({p.device_id for p in desc.pairs if p.measurement == resolved})
    latest = await client.get_latest_measurements(
        device_ids=device_ids, measurements=[resolved]
    )
    values = sorted(latest.values, key=lambda v: v.device_id)
    if not values:
        msg = f"No recent readings of {resolved} at this site."
        return _error_artifact("not_found", msg), msg

    stats = _stats(values)
    spec = TableSpec.model_validate(
        {
            "title": f"Latest {resolved}",
            "columns": [
                {"key": "device", "label": "Device"},
                {"key": "value", "label": resolved},
                {"key": "updated", "label": "Updated"},
            ],
            "rows": [
                {
                    "device": v.device_id,
                    "value": v.value if _is_number(v.value) else str(v.value),
                    "updated": iso_z(v.ts),
                }
                for v in values
            ],
            "dataAsOf": iso_z(now),
            "note": stats,
        }
    )
    art = AnalystArtifact.model_validate(
        {"kind": "table", "spec": spec.model_dump(by_alias=True)}
    )
    newest = max(v.ts for v in values)
    summary = (
        f"{resolved}, latest across {len(values)} devices: {stats}. "
        f"Per device: {_per_device(values)}. "
        f"Newest reading {iso_z(newest)} ({_age(now, newest)})."
    )
    return art, summary


async def get_latest_value(ctx: RunContext[_TelemetryDeps], measurement: str) -> str:
    """Current reading of one measurement across every device that reports it.

    For "right now" / "current" / "latest" questions — "what's the fleet
    state of charge", "current power draw", "latest temperature" — call
    this ONCE instead of describe_site + query_timeseries per device. Pass
    the measurement as the user said it ("state of charge" is fine); it
    returns the per-device values, avg/min/max, and how old the newest
    reading is, so you can answer directly. Not for trends over time —
    use query_timeseries for those.

    Args:
        measurement: Measurement name, e.g. "state_of_charge" or "state of charge".
    """
    client = ctx.deps.server
    assert isinstance(client, ServerClient)
    art, summary = await build_latest_value(client, measurement)
    ctx.deps.artifacts.append(art)
    return summary
