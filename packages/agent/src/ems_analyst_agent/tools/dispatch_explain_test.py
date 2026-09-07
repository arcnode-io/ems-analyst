"""Unit tests for compute_dispatch_stats — pure arithmetic, no network.

Numbers are hand-verified (see module docstring in dispatch_explain.py
for the worked example) — this is the money math Baker will scrutinize
on a recorded demo, so exact values matter more than usual.
"""

from datetime import UTC, datetime, timedelta

from .dispatch_explain import compute_dispatch_stats

_T0 = datetime(2026, 1, 1, 0, tzinfo=UTC)


def _hours(*values: float) -> dict[datetime, float]:
    """{t0+i hours: values[i]} for i in range(len(values))."""
    return {_T0 + timedelta(hours=i): v for i, v in enumerate(values)}


class TestComputeDispatchStats:
    """One worked example: baseline prices, a 3h peak, one earlier charge hour."""

    def test_discharge_at_peak_and_earlier_charge(self) -> None:
        # Arrange — Q3 of this series is 146.75, cleanly separating the
        # 3-hour 180/190/185 spike (hours 8-10) from everything else.
        dam_price = _hours(40, 41, 42, 43, 44, 45, 46, 47, 180, 190, 185, 44)
        rtm_price = dict(dam_price)
        dam_disp = _hours(0, 0, 0, 0, 0, 0, 0, 0, 1_500_000, 1_800_000, 1_600_000, 0)
        rtm_disp = _hours(-200_000, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        soc = _hours(50, 50, 50, 50, 50, 50, 50, 50, 45, 40, 35, 35)

        # Act
        stats = compute_dispatch_stats(
            dam_price=dam_price,
            rtm_price=rtm_price,
            dam_dispatch_w=dam_disp,
            rtm_dispatch_w=rtm_disp,
            soc=soc,
        )

        # Assert — peak window found, sign confirmed, revenue split correctly
        assert stats.median_price == 44.5
        assert stats.peak_start == _T0 + timedelta(hours=8)
        assert stats.peak_end == _T0 + timedelta(hours=10)
        assert stats.peak_avg_price == 185.0
        assert stats.peak_dispatch_confirmed is True
        assert stats.discharge_hours == 3
        assert stats.charge_hours == 1
        assert stats.discharge_revenue == 908.0
        assert stats.charge_cost == 8.0
        assert stats.net_revenue == 900.0
        assert stats.discharge_avg_price == 185.0
        assert stats.charge_avg_price == 40.0
        assert stats.spread == 145.0
        assert stats.soc_min == 35.0
        assert stats.soc_max == 50.0

    def test_no_discharge_hours_gives_none_avg_and_zero_revenue(self) -> None:
        # Arrange — flat dispatch, nothing ever crosses the idle epsilon
        dam_price = _hours(40, 41, 42)
        rtm_price = dict(dam_price)
        dam_disp = _hours(0, 0, 0)
        rtm_disp = _hours(0, 0, 0)
        soc = _hours(50, 50, 50)

        # Act
        stats = compute_dispatch_stats(
            dam_price=dam_price,
            rtm_price=rtm_price,
            dam_dispatch_w=dam_disp,
            rtm_dispatch_w=rtm_disp,
            soc=soc,
        )

        # Assert
        assert stats.discharge_hours == 0
        assert stats.charge_hours == 0
        assert stats.discharge_revenue == 0.0
        assert stats.charge_cost == 0.0
        assert stats.discharge_avg_price is None
        assert stats.charge_avg_price is None
        assert stats.spread is None
