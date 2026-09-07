"""explain_dispatch artifact builder — fetches series, shapes two charts.

Two time-aligned `line` artifacts (DAM price, then net dispatch) instead
of one dual-axis chart — LineSpec is single-axis today and a schema
change wasn't worth it for the demo (see
HANDOFF-analyst-explain-dispatch-2026-09-07.md). Both share the same
start/end and xAxis.kind="time", so they align vertically on the HMI
canvas and read as one figure. All the money math lives in
`compute_dispatch_stats` (dispatch_explain.py) — this module just fetches
and renders it.
"""

from datetime import UTC, datetime, timedelta
from typing import Final

from ..isotime import iso_z
from ..schemas import AnalystArtifact, LineSpec
from ..server_client import ServerClient
from ._common import _error_artifact, _fmt_window
from .dispatch_explain import DispatchStats, compute_dispatch_stats
from .site_analytics import _bucketed_series

_MARKET_DEVICE_ID: Final[str] = "market_01"
_DAM_PRICE_M: Final[str] = "dam_clearing_price_usd_per_mwh"
_RTM_PRICE_M: Final[str] = "rtm_clearing_price_usd_per_mwh"
_DAM_DISPATCH_M: Final[str] = "dam_dispatch_w"
_RTM_DISPATCH_M: Final[str] = "rtm_dispatch_w"
_SOC_M: Final[str] = "state_of_charge"


async def build_explain_dispatch(
    client: ServerClient, device_id: str, window: timedelta
) -> tuple[list[AnalystArtifact], DispatchStats | None]:
    """Two time-aligned line artifacts + the stats behind them.

    Stats are returned alongside the artifacts (not just baked into their
    `note`s) because the RunContext wrapper needs every number for its
    LLM-visible return string — the model never sees the artifacts' data,
    only that string (same reason as `get_device_status`).
    """
    end = datetime.now(UTC)
    start = end - window
    dam_price = await _bucketed_series(
        client, _MARKET_DEVICE_ID, _DAM_PRICE_M, start, end
    )
    if not dam_price:
        return [
            _error_artifact(
                "not_found",
                f"No {_DAM_PRICE_M} data over the last {_fmt_window(window)}.",
            )
        ], None
    rtm_price = await _bucketed_series(
        client, _MARKET_DEVICE_ID, _RTM_PRICE_M, start, end
    )
    dam_disp = await _bucketed_series(client, device_id, _DAM_DISPATCH_M, start, end)
    rtm_disp = await _bucketed_series(client, device_id, _RTM_DISPATCH_M, start, end)
    soc = await _bucketed_series(client, device_id, _SOC_M, start, end)
    stats = compute_dispatch_stats(dam_price, rtm_price, dam_disp, rtm_disp, soc)

    price_spec = LineSpec.model_validate(
        {
            "title": f"DAM clearing price, last {_fmt_window(window)}",
            "xAxis": {"label": "Time", "kind": "time"},
            "yAxis": {"label": "Price", "unit": "$/MWh"},
            "series": [
                {
                    "label": "$/MWh",
                    "points": [
                        {"x": ts.isoformat().replace("+00:00", "Z"), "y": p}
                        for ts, p in sorted(dam_price.items())
                    ],
                }
            ],
            "thresholds": [
                {"label": "window median", "y": stats.median_price, "severity": "warn"}
            ],
            "dataAsOf": iso_z(),
            "note": _price_note(device_id, stats, window),
        }
    )
    net_by_ts = {
        ts: (dam_disp.get(ts, 0.0) + rtm_disp.get(ts, 0.0)) / 1000.0
        for ts in set(dam_disp) | set(rtm_disp)
    }
    dispatch_spec = LineSpec.model_validate(
        {
            "title": f"{device_id} net dispatch, last {_fmt_window(window)}",
            "xAxis": {"label": "Time", "kind": "time"},
            "yAxis": {"label": "Net dispatch", "unit": "kW"},
            "series": [
                {
                    "label": "kW (+discharge / -charge)",
                    "points": [
                        {"x": ts.isoformat().replace("+00:00", "Z"), "y": v}
                        for ts, v in sorted(net_by_ts.items())
                    ],
                }
            ],
            "thresholds": [{"label": "idle", "y": 0.0, "severity": "warn"}],
            "dataAsOf": iso_z(),
            "note": (
                f"discharged {stats.discharge_hours}h, charged {stats.charge_hours}h "
                f"over the window"
            ),
        }
    )
    # Dispatch first, price last: the HMI canvas renders a turn's artifact
    # list newest-first, and "price spike -> battery responds" reads right
    # with price on top.
    artifacts = [
        AnalystArtifact.model_validate(
            {"kind": "line", "spec": dispatch_spec.model_dump(by_alias=True)}
        ),
        AnalystArtifact.model_validate(
            {"kind": "line", "spec": price_spec.model_dump(by_alias=True)}
        ),
    ]
    return artifacts, stats


def _price_note(device_id: str, stats: DispatchStats, window: timedelta) -> str:
    """One-line takeaway for the price chart — the demo's headline claim."""
    if stats.peak_start is None or stats.peak_avg_price is None:
        return f"no clear price peak over the last {_fmt_window(window)}"
    span = f"{stats.peak_start:%H:%M}-{stats.peak_end:%H:%M}" if stats.peak_end else ""
    action = "discharged" if stats.peak_dispatch_confirmed else "did not discharge"
    return (
        f"{device_id} {action} across the {span} peak "
        f"(avg ${stats.peak_avg_price:.0f} vs ${stats.median_price:.0f} median); "
        f"net arbitrage ≈ ${stats.net_revenue:,.0f}"
    )
