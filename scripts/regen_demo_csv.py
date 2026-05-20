"""Regenerate the demo measurements CSV from 30d of real ERCOT DAM SPP.

Pulls 30 days of recent HB_NORTH DAM SPP from beta `timeseries_data`,
generates plausible BESS arbitrage dispatch (charge below median price,
discharge above) + grid intertie + compute load + status + CDU temps,
writes to `src/ems_analyst_agent/demo_data/measurements.csv`.

The CSV uses absolute timestamps; `demo_seed.py` time-shifts them so
the most recent row aligns with `now()` at startup — keeps demos
showing "last 30 days" without periodic regen.

Run:
    TIMESERIES_URL='postgres://...:5432/postgres' \
      uv run python scripts/regen_demo_csv.py
"""

import csv
import logging
import math
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Final

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_SITE_ID: Final[str] = "demo-site"
_OUTPUT_CSV: Final[Path] = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "ems_analyst_agent"
    / "demo_data"
    / "measurements.csv"
)
# Per HMI compute_module template bounds + view.json sizing_params.
_COMPUTE_BASE_KW: Final[float] = 1000.0
_COMPUTE_AMP_KW: Final[float] = 200.0
_BESS_MAX_W: Final[float] = 2_000_000.0  # ±2 MW per module from HMI template


def _pull_prices() -> list[tuple[datetime, float]]:
    """Read last 30 days of DAM SPP from timeseries_data (beta)."""
    conn = psycopg2.connect(os.environ["TIMESERIES_URL"])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ts, value FROM timeseries_data "
                "WHERE ts >= now() - interval '30 days' ORDER BY ts"
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [(r[0], float(r[1])) for r in rows]


def _bess_dispatch_w(price: float, median: float, soc: float, jitter: float) -> float:
    """Arbitrage rule: discharge above median if SoC > 20%, charge below if < 90%.

    Magnitude scales with |price - median| up to ±_BESS_MAX_W.
    `jitter` ∈ [0, 1] adds variation between the two modules.
    """
    delta = price - median
    scale = min(abs(delta) / max(median, 1.0), 1.0)
    magnitude = _BESS_MAX_W * scale * (0.7 + 0.6 * jitter)
    if delta > 0 and soc > 20.0:
        return magnitude  # discharge
    if delta < 0 and soc < 90.0:
        return -magnitude  # charge
    return 0.0


def _update_soc(soc: float, active_power_w: float) -> float:
    """SoC update: charging (negative active_power) adds, discharging subtracts.

    Capacity = 4000 kWh per module (HMI sizing). Round-trip eff 91.7%
    (HMI BESS spec). Charge gain dampened; discharge loss inflated.
    """
    energy_kwh = -active_power_w / 1000.0
    capacity_kwh = 4000.0
    if energy_kwh > 0:  # charging
        energy_kwh *= 0.957
    else:  # discharging
        energy_kwh *= 1.090
    return max(10.0, min(95.0, soc + energy_kwh / capacity_kwh * 100.0))


def _compute_load_kw(ts: datetime) -> float:
    """Diurnal compute load: peak mid-day, trough at dawn."""
    hour = ts.hour + ts.minute / 60.0
    diurnal = math.sin((hour - 5) / 24.0 * 2 * math.pi)
    noise = random.gauss(0, 30)
    return max(300.0, _COMPUTE_BASE_KW + _COMPUTE_AMP_KW * diurnal + noise)


def _write_row(
    rows: list[list[object]],
    ts: datetime,
    device_id: str,
    measurement: str,
    unit: str,
    value: object,
) -> None:
    rows.append(
        [
            ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            _SITE_ID,
            device_id,
            measurement,
            unit,
            value if not isinstance(value, str) else f'"{value}"',
        ]
    )


def generate(prices: list[tuple[datetime, float]]) -> list[list[object]]:
    """Generate one CSV row per (ts, device, measurement).

    Includes a synthetic `market_01` device carrying DAM + RTM clearing
    prices. Architecturally awkward (market data isn't site telemetry)
    but pragmatic for the demo: lets the markets revenue tool read
    everything through the same measurements path the HMI uses.
    Replace with a proper /market/prices server endpoint when one site
    isn't enough to cover the use case.
    """
    if not prices:
        raise RuntimeError("no DAM SPP rows in timeseries_data — run model ETL first")
    random.seed(42)
    price_values = [p for _, p in prices]
    median = sorted(price_values)[len(price_values) // 2]
    log.info("median DAM SPP = %.2f over %d hours", median, len(prices))
    rows: list[list[object]] = [
        ["ts", "site_id", "device_id", "measurement", "unit", "value"]
    ]
    soc_01 = 60.0
    soc_02 = 60.0
    for ts, price in prices:
        # BESS dispatch (DAM) — price-following
        d01 = _bess_dispatch_w(price, median, soc_01, jitter=0.3)
        d02 = _bess_dispatch_w(price, median, soc_02, jitter=0.7)
        # RTM perturbation — small intra-hour adjustment
        r01 = random.gauss(0, 50_000)
        r02 = random.gauss(0, 50_000)
        ap01 = d01 + r01
        ap02 = d02 + r02
        soc_01 = _update_soc(soc_01, ap01)
        soc_02 = _update_soc(soc_02, ap02)
        # Compute load
        compute_kw = _compute_load_kw(ts)
        # Grid intertie residual: positive = importing from grid
        grid_w = compute_kw * 1000.0 - (ap01 + ap02)
        # Per-device rows
        for dev, soc, ap, dam_w, rtm_w in (
            ("bess_module_01", soc_01, ap01, d01, r01),
            ("bess_module_02", soc_02, ap02, d02, r02),
        ):
            _write_row(rows, ts, dev, "state_of_charge", "percent", round(soc, 2))
            _write_row(rows, ts, dev, "active_power", "watts", round(ap, 1))
            _write_row(rows, ts, dev, "dam_dispatch_w", "watts", round(dam_w, 1))
            _write_row(rows, ts, dev, "rtm_dispatch_w", "watts", round(rtm_w, 1))
        _write_row(
            rows,
            ts,
            "compute_module_01",
            "active_power",
            "watts",
            round(compute_kw * 1000, 1),
        )
        _write_row(
            rows,
            ts,
            "compute_module_01",
            "gpu_utilization",
            "percent",
            round(min(100.0, compute_kw / 12.0), 2),
        )
        _write_row(
            rows, ts, "revenue_meter_01", "settlement_power", "watts", round(grid_w, 1)
        )
        _write_row(
            rows,
            ts,
            "cdu_01",
            "inlet_temperature",
            "celsius",
            round(random.gauss(20, 0.8), 2),
        )
        _write_row(
            rows,
            ts,
            "cdu_01",
            "outlet_temperature",
            "celsius",
            round(random.gauss(33, 1.2), 2),
        )
        # Market prices on synthetic device. RTM = DAM + intra-hour noise
        # (we don't pull real RTM to stay under gridstatus daily quota).
        _write_row(
            rows,
            ts,
            "market_01",
            "dam_clearing_price_usd_per_mwh",
            "usd_per_mwh",
            round(price, 3),
        )
        _write_row(
            rows,
            ts,
            "market_01",
            "rtm_clearing_price_usd_per_mwh",
            "usd_per_mwh",
            round(price + random.gauss(0, 1.5), 3),
        )
    # One status row per device at the latest ts — keeps list_devices_where
    # finding distinct devices with severity variety for the demo table.
    latest = prices[-1][0]
    for dev, status in (
        ("bess_module_01", "ok"),
        ("bess_module_02", "warn"),
        ("compute_module_01", "ok"),
        ("revenue_meter_01", "ok"),
        ("cdu_01", "alarm"),
    ):
        _write_row(rows, latest, dev, "status", "enum", status)
    return rows


def main() -> None:
    """CLI entry: pull DAM SPP, generate demo rows, write CSV."""
    prices = _pull_prices()
    rows = generate(prices)
    _OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with _OUTPUT_CSV.open("w", newline="") as f:
        csv.writer(f).writerows(rows)
    log.info("wrote %d rows to %s", len(rows) - 1, _OUTPUT_CSV)


if __name__ == "__main__":
    sys.exit(main() or 0)
