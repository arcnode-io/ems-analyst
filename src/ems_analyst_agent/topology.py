"""HMI device template → energy category mapping.

The HMI publishes a static `view.json` topology with `template` per
device (bess_module, compute_module, revenue_meter, etc.). The agent
needs to know which devices contribute to which side of the energy
ledger (BESS source/sink, grid intertie, compute load) for
`query_energy_breakdown` + `query_markets`.

Until the server exposes `/sites/{id}/topology`, the agent infers
template from the HMI's documented device_id prefixes. Single source of
truth: `ems-hmi/packages/web/public/api/topology/view.json`.
"""

from typing import Final

EnergyCategory = str  # "bess" | "grid_intertie" | "compute_load" | "compute_support" | "metadata" | "market"

# HMI template name → energy attribution category.
_TEMPLATE_TO_CATEGORY: Final[dict[str, EnergyCategory]] = {
    "bess_module": "bess",
    "compute_module": "compute_load",
    "revenue_meter": "grid_intertie",
    "grid_module": "metadata",
    "operating_envelope": "metadata",
    "line_rating": "metadata",
    "cdu": "compute_support",
    # synthetic device for demo market prices
    "market": "market",
}

# device_id prefix → template inference. Mirrors HMI's view.json
# device_id format. Update if HMI changes the convention.
_DEVICE_PREFIX_TO_TEMPLATE: Final[dict[str, str]] = {
    "bess_module_": "bess_module",
    "compute_module_": "compute_module",
    "grid_module_": "grid_module",
    "revenue_meter_": "revenue_meter",
    "operating_envelope_": "operating_envelope",
    "line_rating_": "line_rating",
    "cdu_": "cdu",
    "market_": "market",
}


def template_of(device_id: str) -> str | None:
    """HMI template name for a device, or None if no match."""
    for prefix, template in _DEVICE_PREFIX_TO_TEMPLATE.items():
        if device_id.startswith(prefix):
            return template
    return None


def category_of(device_id: str) -> EnergyCategory | None:
    """Energy attribution category for a device, or None if no match."""
    template = template_of(device_id)
    return _TEMPLATE_TO_CATEGORY.get(template) if template else None


def devices_in_category(device_ids: list[str], category: EnergyCategory) -> list[str]:
    """Filter a list of device_ids to those in `category`."""
    return sorted({d for d in device_ids if category_of(d) == category})
