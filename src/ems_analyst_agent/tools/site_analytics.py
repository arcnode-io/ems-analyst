"""Site analytics builders — markets revenue + energy breakdown.

Values read through ServerClient. Device→category attribution comes
from the DTM (DtmView) fetched from ems-device-api — the source of
truth for which devices are BESS / grid / compute.
"""

from datetime import UTC, datetime, timedelta
from typing import Final, Literal

from ..device_api import DtmView
from ..schemas import AnalystArtifact, BarSpec, PieSpec
from ..server_client import ServerClient
from .telemetry import _error_artifact, _now

_MARKET_DEVICE_ID: Final[str] = "market_01"
_DAM_PRICE_M: Final[str] = "dam_clearing_price_usd_per_mwh"
_RTM_PRICE_M: Final[str] = "rtm_clearing_price_usd_per_mwh"
_DAM_DISPATCH_M: Final[str] = "dam_dispatch_w"
_RTM_DISPATCH_M: Final[str] = "rtm_dispatch_w"


async def _bucketed_series(
    client: ServerClient,
    site_id: str,
    device_id: str,
    measurement: str,
    start: datetime,
    end: datetime,
) -> dict[datetime, float]:
    """Hourly bucketed series as {ts: value} dict (null buckets dropped)."""
    series = await client.get_measurements(
        site_id=site_id,
        device_id=device_id,
        measurement=measurement,
        start=start,
        end=end,
    )
    return {p.ts: p.value for p in series.points if p.value is not None}


def _revenue(
    dispatch_w_by_ts: dict[datetime, float],
    price_by_ts: dict[datetime, float],
) -> float:
    """Σ over hours of (W → MW) * ($/MWh * 1h) = $."""
    return sum(
        (dispatch_w_by_ts[ts] / 1_000_000.0) * price_by_ts[ts]
        for ts in dispatch_w_by_ts
        if ts in price_by_ts
    )


async def build_markets(
    client: ServerClient,
    dtm: DtmView,
    site_id: str,
    window: timedelta,
) -> AnalystArtifact:
    """Revenue per market over the window. BarSpec with DAM + RTM bars.

    BESS devices come from the DTM (template == bess_module).
    """
    end = datetime.now(UTC)
    start = end - window
    bess = dtm.devices_in_category("bess")
    if not bess:
        return _error_artifact(
            "not_found", f"No BESS devices in the topology for {site_id}."
        )
    dam_price = await _bucketed_series(
        client, site_id, _MARKET_DEVICE_ID, _DAM_PRICE_M, start, end
    )
    rtm_price = await _bucketed_series(
        client, site_id, _MARKET_DEVICE_ID, _RTM_PRICE_M, start, end
    )
    dam_total = 0.0
    rtm_total = 0.0
    for dev in bess:
        dam_disp = await _bucketed_series(
            client, site_id, dev, _DAM_DISPATCH_M, start, end
        )
        rtm_disp = await _bucketed_series(
            client, site_id, dev, _RTM_DISPATCH_M, start, end
        )
        dam_total += _revenue(dam_disp, dam_price)
        rtm_total += _revenue(rtm_disp, rtm_price)
    spec = BarSpec.model_validate(
        {
            "title": f"Revenue by market (last {window})",
            "xAxis": {"label": "Market", "categories": ["DAM", "RTM"]},
            "yAxis": {"label": "Revenue", "unit": "USD"},
            "series": [
                {
                    "label": "Revenue",
                    "values": [round(dam_total, 2), round(rtm_total, 2)],
                }
            ],
            "dataAsOf": _now(),
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "bar", "spec": spec.model_dump(by_alias=True)}
    )


async def _energy_per_device(
    client: ServerClient,
    site_id: str,
    device_id: str,
    measurement: str,
    start: datetime,
    end: datetime,
    sign_filter: Literal["positive", "negative", "abs"],
) -> float:
    """Integrate power_w → kWh over window, filtered by sign convention."""
    series = await _bucketed_series(client, site_id, device_id, measurement, start, end)
    if sign_filter == "positive":
        return sum(v for v in series.values() if v > 0) / 1000.0
    if sign_filter == "negative":
        return sum(-v for v in series.values() if v < 0) / 1000.0
    return sum(abs(v) for v in series.values()) / 1000.0


async def build_energy_breakdown(
    client: ServerClient,
    dtm: DtmView,
    site_id: str,
    window: timedelta,
    by: Literal["source", "destination"] = "source",
) -> AnalystArtifact:
    """Energy by source (or destination) over window. PieSpec.

    Device categories come from the DTM. Sign conventions:
    - source: BESS discharge (active_power > 0), grid import
      (settlement_power > 0).
    - destination: compute load (active_power abs), BESS charge
      (active_power < 0), grid export (settlement_power < 0).
    """
    end = datetime.now(UTC)
    start = end - window
    slices: list[dict[str, float | str]] = []
    if by == "source":
        for dev in dtm.devices_in_category("bess"):
            kwh = await _energy_per_device(
                client, site_id, dev, "active_power", start, end, "positive"
            )
            slices.append({"label": f"{dev} discharge", "value": round(kwh, 2)})
        for dev in dtm.devices_in_category("grid_intertie"):
            kwh = await _energy_per_device(
                client, site_id, dev, "settlement_power", start, end, "positive"
            )
            slices.append({"label": "Grid import", "value": round(kwh, 2)})
    else:
        for dev in dtm.devices_in_category("compute_load"):
            kwh = await _energy_per_device(
                client, site_id, dev, "active_power", start, end, "abs"
            )
            slices.append({"label": "Compute load", "value": round(kwh, 2)})
        for dev in dtm.devices_in_category("bess"):
            kwh = await _energy_per_device(
                client, site_id, dev, "active_power", start, end, "negative"
            )
            slices.append({"label": f"{dev} charge", "value": round(kwh, 2)})
        for dev in dtm.devices_in_category("grid_intertie"):
            kwh = await _energy_per_device(
                client, site_id, dev, "settlement_power", start, end, "negative"
            )
            slices.append({"label": "Grid export", "value": round(kwh, 2)})
    # Drop zero slices to keep the pie readable.
    slices = [s for s in slices if isinstance(s["value"], float) and s["value"] > 0]
    if not slices:
        return _error_artifact(
            "not_found", f"No energy {by} data over the last {window}."
        )
    spec = PieSpec.model_validate(
        {
            "title": f"Energy by {by} (last {window})",
            "unit": "kWh",
            "slices": slices,
            "dataAsOf": _now(),
        }
    )
    return AnalystArtifact.model_validate(
        {"kind": "pie", "spec": spec.model_dump(by_alias=True)}
    )
