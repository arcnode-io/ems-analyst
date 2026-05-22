"""Timeseries + site-inventory artifact builders, backed by ServerClient.

`build_timeseries` charts a historian series; `build_site_description`
tables the queryable-data inventory. Markets revenue + energy breakdown
live in `site_analytics.py`; RunContext wrappers in `telemetry_tools.py`.
"""

from datetime import UTC, datetime, timedelta

from ..isotime import iso_z
from ..schemas import AnalystArtifact, LineSpec, TableSpec
from ..server_client import Aggregation, ServerClient
from ._common import _error_artifact, _fmt_window


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
    note = f"{min(ys):g}-{max(ys):g} {series.unit}, latest {ys[-1]:g}" if ys else None
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
