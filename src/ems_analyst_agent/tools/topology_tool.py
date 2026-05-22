"""get_topology tool — site device layout from the DTM.

`build_topology` shapes a DtmView into a TableSpec; `get_topology` is
the thin RunContext wrapper the Agent registers. Fetches the Device
Topology Manifest from ems-device-api (or the bundled demo mock).
"""

from pydantic_ai import RunContext

from ..device_api import DeviceApiClient, DtmView
from ..schemas import AnalystArtifact, TableSpec
from .telemetry import _TelemetryDeps, _error_artifact, _now


def build_topology(dtm: DtmView) -> AnalystArtifact:
    """Shape a DtmView into a device table (device, name, template, parent)."""
    if not dtm.devices:
        return _error_artifact("not_found", "Topology has no devices.")
    rows: list[dict[str, str | None]] = [
        {
            "device": d.device_id,
            "name": d.display_name,
            "template": d.template,
            "parent": d.parent,
        }
        for d in sorted(dtm.devices.values(), key=lambda d: d.device_id)
    ]
    spec = TableSpec.model_validate(
        {
            "title": "Site topology",
            "columns": [
                {"key": "device", "label": "Device"},
                {"key": "name", "label": "Name"},
                {"key": "template", "label": "Template"},
                {"key": "parent", "label": "Parent"},
            ],
            "rows": rows,
            "dataAsOf": _now(),
            "note": f"{len(rows)} devices in the topology",
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "table", "spec": spec.model_dump(by_alias=True)}
    )


async def get_topology(ctx: RunContext[_TelemetryDeps]) -> str:
    """Site device topology — every device, its template, and parent.

    Call this to answer questions about site layout, what equipment
    exists, or how devices roll up (parent chains).
    """
    client = ctx.deps.device_api
    assert isinstance(client, DeviceApiClient)
    dtm = await client.get_topology()
    art = build_topology(dtm)
    ctx.deps.artifacts.append(art)
    if art.kind == "error":
        return "Topology is empty."
    return f"Returned topology — {len(dtm.devices)} devices."
