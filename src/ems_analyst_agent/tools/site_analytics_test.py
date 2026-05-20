"""Unit tests for site_analytics builders — markets revenue + energy pie.

Fakes ServerClient so we exercise the artifact-shaping math without
spinning Postgres. ServerClient HTTP behaviour itself is pook-tested in
tests/test_server_client.py.
"""

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from ..schemas import BarSpec, PieSpec
from ..server_client import (
    MeasurementPair,
    MeasurementPoint,
    MeasurementSeries,
    ServerClient,
    SiteDescription,
)
from .site_analytics import build_energy_breakdown, build_markets


class _FakeServer:
    """Returns canned responses keyed on (device_id, measurement)."""

    def __init__(
        self,
        pairs: list[MeasurementPair],
        series: dict[tuple[str, str], list[tuple[datetime, float]]],
    ) -> None:
        self._pairs = pairs
        self._series = series

    async def describe_site(self, site_id: str) -> SiteDescription:
        return SiteDescription(site_id=site_id, pairs=self._pairs)

    async def get_measurements(
        self,
        site_id: str,
        device_id: str,
        measurement: str,
        **_unused: object,
    ) -> MeasurementSeries:
        """Return canned series for (device_id, measurement); ignore start/end/agg."""
        key = (device_id, measurement)
        pts = [MeasurementPoint(ts=ts, value=v) for ts, v in self._series.get(key, [])]
        return MeasurementSeries(
            site_id=site_id,
            device_id=device_id,
            measurement=measurement,
            unit="",
            points=pts,
        )


def _hourly(start: datetime, values: list[float]) -> list[tuple[datetime, float]]:
    """Emit (ts, value) pairs at hourly cadence starting at `start`."""
    return [(start + timedelta(hours=i), v) for i, v in enumerate(values)]


class TestBuildMarkets:
    @pytest.mark.asyncio
    async def test_revenue_equals_dispatch_mwh_times_price(self) -> None:
        # Arrange — 1 BESS, 3 hourly buckets, constant price $50/MWh,
        # constant 1MW DAM dispatch + 0.5MW RTM dispatch.
        start = datetime(2026, 5, 1, tzinfo=UTC)
        pairs = [
            MeasurementPair(
                device_id="bess_module_01", measurement="dam_dispatch_w", samples=3
            ),
        ]
        series = {
            ("bess_module_01", "dam_dispatch_w"): _hourly(start, [1_000_000.0] * 3),
            ("bess_module_01", "rtm_dispatch_w"): _hourly(start, [500_000.0] * 3),
            ("market_01", "dam_clearing_price_usd_per_mwh"): _hourly(start, [50.0] * 3),
            ("market_01", "rtm_clearing_price_usd_per_mwh"): _hourly(start, [60.0] * 3),
        }
        fake = _FakeServer(pairs, series)

        # Act
        art = await build_markets(
            cast(ServerClient, fake), site_id="demo-site", window=timedelta(hours=3)
        )

        # Assert — DAM: 3 hours * 1 MWh * $50 = $150. RTM: 3*0.5*$60 = $90.
        assert art.kind == "bar"
        assert isinstance(art.spec, BarSpec)
        assert art.spec.series[0].values == [150.0, 90.0]

    @pytest.mark.asyncio
    async def test_no_bess_returns_error_artifact(self) -> None:
        # Arrange — describe_site finds no devices dispatching in DAM
        fake = _FakeServer([], {})

        # Act
        art = await build_markets(
            cast(ServerClient, fake), site_id="demo-site", window=timedelta(hours=3)
        )

        # Assert
        assert art.kind == "error"


class TestBuildEnergyBreakdown:
    @pytest.mark.asyncio
    async def test_source_pie_sums_bess_discharge_and_grid_import(self) -> None:
        # Arrange — BESS discharges 1 MW for 2h, grid imports 500kW for 2h.
        start = datetime(2026, 5, 1, tzinfo=UTC)
        pairs = [
            MeasurementPair(
                device_id="bess_module_01", measurement="active_power", samples=2
            ),
            MeasurementPair(
                device_id="revenue_meter_01", measurement="settlement_power", samples=2
            ),
        ]
        series = {
            ("bess_module_01", "active_power"): _hourly(
                start, [1_000_000.0, 1_000_000.0]
            ),
            ("revenue_meter_01", "settlement_power"): _hourly(
                start, [500_000.0, 500_000.0]
            ),
        }
        fake = _FakeServer(pairs, series)

        # Act
        art = await build_energy_breakdown(
            cast(ServerClient, fake),
            site_id="demo-site",
            window=timedelta(hours=2),
            by="source",
        )

        # Assert — BESS 2000 kWh, Grid import 1000 kWh
        assert art.kind == "pie"
        assert isinstance(art.spec, PieSpec)
        by_label = {s.label: s.value for s in art.spec.slices}
        assert by_label["bess_module_01 discharge"] == 2000.0
        assert by_label["Grid import"] == 1000.0

    @pytest.mark.asyncio
    async def test_destination_pie_sums_compute_and_bess_charge(self) -> None:
        # Arrange — compute draws 800 kW for 2h, BESS charges -500 kW for 2h.
        start = datetime(2026, 5, 1, tzinfo=UTC)
        pairs = [
            MeasurementPair(
                device_id="compute_module_01", measurement="active_power", samples=2
            ),
            MeasurementPair(
                device_id="bess_module_01", measurement="active_power", samples=2
            ),
        ]
        series = {
            ("compute_module_01", "active_power"): _hourly(
                start, [800_000.0, 800_000.0]
            ),
            ("bess_module_01", "active_power"): _hourly(
                start, [-500_000.0, -500_000.0]
            ),
            ("revenue_meter_01", "settlement_power"): _hourly(
                start, [-100_000.0, -100_000.0]
            ),
        }
        fake = _FakeServer(
            [
                *pairs,
                MeasurementPair(
                    device_id="revenue_meter_01",
                    measurement="settlement_power",
                    samples=2,
                ),
            ],
            series,
        )

        # Act
        art = await build_energy_breakdown(
            cast(ServerClient, fake),
            site_id="demo-site",
            window=timedelta(hours=2),
            by="destination",
        )

        # Assert
        assert art.kind == "pie"
        assert isinstance(art.spec, PieSpec)
        by_label = {s.label: s.value for s in art.spec.slices}
        assert by_label["Compute load"] == 1600.0
        assert by_label["bess_module_01 charge"] == 1000.0
        assert by_label["Grid export"] == 200.0

    @pytest.mark.asyncio
    async def test_no_data_returns_error_artifact(self) -> None:
        # Arrange
        fake = _FakeServer([], {})

        # Act
        art = await build_energy_breakdown(
            cast(ServerClient, fake),
            site_id="demo-site",
            window=timedelta(hours=2),
            by="source",
        )

        # Assert
        assert art.kind == "error"
