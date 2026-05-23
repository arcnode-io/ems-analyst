"""Client for ems-device-api — the canonical Device Topology Manifest.

The agent fetches the sanitized DTM projection (`GET /topology/view`)
to learn which devices exist + their templates. Same JSON the HMI
consumes. device-api runs as a peer container on the compose network.

ENV=demo → read the bundled demo_data/topology_view.json instead of
hitting device-api (same mock pattern as the measurements CSV).

`template_category` maps an HMI device template to an energy-ledger
category — that's agent-side semantic (the DTM says a device has
template `bess_module`; "bess_module is an energy source" is our call).
"""

import json
import logging
import os
from importlib import resources
from typing import Final

import httpx
from pydantic import BaseModel

log = logging.getLogger(__name__)

_DEVICE_API_URL_ENV: Final[str] = "DEVICE_API_URL"
_ENV_ENV: Final[str] = "ENV"
_HTTP_TIMEOUT: Final[float] = 15.0
_PKG_DATA: Final[str] = "ems_analyst_agent.demo_data"
_DEMO_TOPOLOGY: Final[str] = "topology_view.json"

# HMI template → energy-ledger category. Agent-side semantic.
_TEMPLATE_TO_CATEGORY: Final[dict[str, str]] = {
    "bess_module": "bess",
    "compute_module": "compute_load",
    "revenue_meter": "grid_intertie",
    "grid_module": "metadata",
    "operating_envelope": "metadata",
    "line_rating": "metadata",
    "cdu": "compute_support",
}


class DeviceView(BaseModel):
    """One device in the DTM projection — subset the agent needs."""

    device_id: str
    template: str
    parent: str | None = None
    display_name: str | None = None


class DtmView(BaseModel):
    """Sanitized Device Topology Manifest projection from device-api."""

    deployment_uuid: str
    devices: dict[str, DeviceView]

    def category_of(self, device_id: str) -> str | None:
        """Energy-ledger category for a device, via its DTM template."""
        device = self.devices.get(device_id)
        if device is None:
            return None
        return _TEMPLATE_TO_CATEGORY.get(device.template)

    def devices_in_category(self, category: str) -> list[str]:
        """All device_ids whose template maps to `category`, sorted."""
        return sorted(
            d.device_id
            for d in self.devices.values()
            if _TEMPLATE_TO_CATEGORY.get(d.template) == category
        )


class DeviceApiClient:
    """Fetches the DTM from ems-device-api, or the bundled demo mock."""

    def __init__(self, base_url: str | None = None) -> None:
        """base_url override for tests; production reads DEVICE_API_URL."""
        self._base_url = base_url
        self._demo = os.environ.get(_ENV_ENV) == "demo"

    async def get_topology(self) -> DtmView:
        """Return the DTM. ENV=demo → bundled JSON; else GET /topology/view."""
        if self._demo:
            raw = resources.files(_PKG_DATA).joinpath(_DEMO_TOPOLOGY).read_bytes()
            return DtmView.model_validate(json.loads(raw))
        base = (self._base_url or os.environ[_DEVICE_API_URL_ENV]).rstrip("/")
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as c:
            resp = await c.get(f"{base}/topology/view")
            resp.raise_for_status()
        return DtmView.model_validate(resp.json())
