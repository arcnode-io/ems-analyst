"""Pure price↔dispatch correlation arithmetic — no I/O, no LLM.

`compute_dispatch_stats` takes already-fetched series and returns
deterministic stats: median/peak price, dispatch classification,
revenue split. Artifact assembly (fetching via ServerClient, shaping
the two `line` artifacts) lives in `dispatch_explain_artifact.py` —
split to stay under the 200-line cap.

Worked example (see dispatch_explain_test.py): 12 hourly DAM prices with
a 3h spike (180/190/185) against a ~40-47 baseline. Q3=146.75 cleanly
isolates the spike as "the peak" from the noise floor. The battery
discharges through it and had charged once earlier — net_revenue is
discharge_revenue minus charge_cost, both computed via site_analytics's
existing `_revenue` helper.
"""

import statistics
from datetime import datetime, timedelta
from typing import Final

from pydantic import BaseModel

from .site_analytics import _revenue

# Below this, net dispatch is noise (RTM's gaussian perturbation is
# sigma=50kW in the demo seed) rather than a real charge/discharge signal.
_IDLE_EPSILON_W: Final[float] = 50_000.0


class DispatchStats(BaseModel):
    """Deterministic stats correlating price against a BESS's dispatch.

    All money/price/hour fields are exact arithmetic — nothing here is
    LLM-generated. `None` means "not enough data to say" (e.g. the
    battery never charged in the window), not zero.
    """

    median_price: float
    peak_start: datetime | None
    peak_end: datetime | None
    peak_avg_price: float | None
    peak_dispatch_confirmed: bool
    discharge_hours: int
    charge_hours: int
    discharge_revenue: float
    charge_cost: float
    net_revenue: float
    discharge_avg_price: float | None
    charge_avg_price: float | None
    spread: float | None
    soc_min: float | None
    soc_max: float | None


def _mean(values: list[float]) -> float | None:
    """Average, or None for an empty list — an empty mean is undefined."""
    return sum(values) / len(values) if values else None


def _longest_peak_run(
    prices: dict[datetime, float], threshold: float
) -> list[datetime]:
    """Longest contiguous (hourly) run of timestamps with price >= threshold.

    Ties broken by highest average price — that's the more interesting
    run to name as "the peak" for the demo narration.
    """
    peak_ts = sorted(ts for ts, p in prices.items() if p >= threshold)
    runs: list[list[datetime]] = []
    for ts in peak_ts:
        if runs and ts - runs[-1][-1] == timedelta(hours=1):
            runs[-1].append(ts)
        else:
            runs.append([ts])
    if not runs:
        return []
    best_len = max(len(r) for r in runs)
    longest = [r for r in runs if len(r) == best_len]
    return max(longest, key=lambda r: _mean([prices[ts] for ts in r]) or 0.0)


def compute_dispatch_stats(
    dam_price: dict[datetime, float],
    rtm_price: dict[datetime, float],
    dam_dispatch_w: dict[datetime, float],
    rtm_dispatch_w: dict[datetime, float],
    soc: dict[datetime, float],
) -> DispatchStats:
    """Pure arithmetic: median/peak price, dispatch classification, revenue."""
    median_price = statistics.median(dam_price.values())
    threshold = statistics.quantiles(list(dam_price.values()), n=4)[2]
    peak_run = _longest_peak_run(dam_price, threshold)
    peak_avg_price = _mean([dam_price[ts] for ts in peak_run]) if peak_run else None

    all_ts = set(dam_dispatch_w) | set(rtm_dispatch_w)
    net_by_ts = {
        ts: dam_dispatch_w.get(ts, 0.0) + rtm_dispatch_w.get(ts, 0.0) for ts in all_ts
    }
    discharge_ts = {ts for ts, v in net_by_ts.items() if v > _IDLE_EPSILON_W}
    charge_ts = {ts for ts, v in net_by_ts.items() if v < -_IDLE_EPSILON_W}
    peak_dispatch_confirmed = (
        bool(peak_run)
        and (_mean([net_by_ts.get(ts, 0.0) for ts in peak_run]) or 0.0) > 0
    )

    discharge_revenue = _revenue(
        {ts: dam_dispatch_w[ts] for ts in discharge_ts if ts in dam_dispatch_w},
        dam_price,
    ) + _revenue(
        {ts: rtm_dispatch_w[ts] for ts in discharge_ts if ts in rtm_dispatch_w},
        rtm_price,
    )
    charge_cost = -(
        _revenue(
            {ts: dam_dispatch_w[ts] for ts in charge_ts if ts in dam_dispatch_w},
            dam_price,
        )
        + _revenue(
            {ts: rtm_dispatch_w[ts] for ts in charge_ts if ts in rtm_dispatch_w},
            rtm_price,
        )
    )

    discharge_avg_price = _mean(
        [dam_price[ts] for ts in discharge_ts if ts in dam_price]
    )
    charge_avg_price = _mean([dam_price[ts] for ts in charge_ts if ts in dam_price])
    spread = (
        discharge_avg_price - charge_avg_price
        if discharge_avg_price is not None and charge_avg_price is not None
        else None
    )

    return DispatchStats(
        median_price=median_price,
        peak_start=peak_run[0] if peak_run else None,
        peak_end=peak_run[-1] if peak_run else None,
        peak_avg_price=peak_avg_price,
        peak_dispatch_confirmed=peak_dispatch_confirmed,
        discharge_hours=len(discharge_ts),
        charge_hours=len(charge_ts),
        discharge_revenue=discharge_revenue,
        charge_cost=charge_cost,
        net_revenue=discharge_revenue - charge_cost,
        discharge_avg_price=discharge_avg_price,
        charge_avg_price=charge_avg_price,
        spread=spread,
        soc_min=min(soc.values()) if soc else None,
        soc_max=max(soc.values()) if soc else None,
    )
