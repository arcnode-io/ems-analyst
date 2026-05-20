"""Unit tests for site_analytics builders — markets revenue + energy pie.

Fakes ServerClient for measurement values; device→category attribution
comes from a real DtmView built from fake device rows.
"""

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from ..device_api import DtmView
from ..schemas import BarSpec, PieSpec
from ..server_client import MeasurementPoint, MeasurementSeries, ServerClient
from .site_analytics import build_energy_breakdown, build_markets


def _dtm(templates: dict[str, str]) -> DtmView:
    """Build a DtmView from {device_id: template}."""
    return DtmView.model_validate(
        {
            "deployment_uuid": "00000000-0000-0000-0000-000000000001",
            "devices": {
                dev: {"device_id": dev, "template": tpl, "parent": None}
                for dev, tpl in templates.items()
            },
        }
    )


class _FakeServer:
    """Returns canned measurement series keyed on (device_id, measurement)."""

    def __init__(
        self, series: dict[tuple[str, str], list[tuple[datetime, float]]]
    ) -> None:
        self._series = series

    async def get_measurements(
        self,
        site_id: str,
        device_id: str,
        measurement: str,
        **_unused: object,
    ) -> MeasurementSeries:
        """Canned series for (device_id, measurement); ignore start/end/agg."""
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
        # Arrange — 1 BESS, 3 hourly buckets, $50 DAM / $60 RTM,
        # 1 MW DAM dispatch + 0.5 MW RTM dispatch.
        start = datetime(2026, 5, 1, tzinfo=UTC)
        dtm = _dtm({"bess_module_01": "bess_module"})
        series = {
            ("bess_module_01", "dam_dispatch_w"): _hourly(start, [1_000_000.0] * 3),
            ("bess_module_01", "rtm_dispatch_w"): _hourly(start, [500_000.0] * 3),
            ("market_01", "dam_clearing_price_usd_per_mwh"): _hourly(start, [50.0] * 3),
            ("market_01", "rtm_clearing_price_usd_per_mwh"): _hourly(start, [60.0] * 3),
        }
        fake = _FakeServer(series)

        # Act
        art = await build_markets(
            cast(ServerClient, fake), dtm, "demo-site", timedelta(hours=3)
        )

        # Assert — DAM: 3h * 1 MWh * $50 = $150. RTM: 3 * 0.5 * $60 = $90.
        assert art.kind == "bar"
        assert isinstance(art.spec, BarSpec)
        assert art.spec.series[0].values == [150.0, 90.0]

    @pytest.mark.asyncio
    async def test_no_bess_in_dtm_returns_error_artifact(self) -> None:
        # Arrange — DTM has no bess_module device
        dtm = _dtm({"compute_module_01": "compute_module"})
        fake = _FakeServer({})

        # Act
        art = await build_markets(
            cast(ServerClient, fake), dtm, "demo-site", timedelta(hours=3)
        )

        # Assert
        assert art.kind == "error"


class TestBuildEnergyBreakdown:
    @pytest.mark.asyncio
    async def test_source_pie_sums_bess_discharge_and_grid_import(self) -> None:
        # Arrange — BESS discharges 1 MW for 2h, grid imports 500 kW for 2h.
        start = datetime(2026, 5, 1, tzinfo=UTC)
        dtm = _dtm(
            {
                "bess_module_01": "bess_module",
                "revenue_meter_01": "revenue_meter",
            }
        )
        series = {
            ("bess_module_01", "active_power"): _hourly(
                start, [1_000_000.0, 1_000_000.0]
            ),
            ("revenue_meter_01", "settlement_power"): _hourly(
                start, [500_000.0, 500_000.0]
            ),
        }
        fake = _FakeServer(series)

        # Act
        art = await build_energy_breakdown(
            cast(ServerClient, fake), dtm, "demo-site", timedelta(hours=2), "source"
        )

        # Assert — BESS 2000 kWh, Grid import 1000 kWh
        assert art.kind == "pie"
        assert isinstance(art.spec, PieSpec)
        by_label = {s.label: s.value for s in art.spec.slices}
        assert by_label["bess_module_01 discharge"] == 2000.0
        assert by_label["Grid import"] == 1000.0

    @pytest.mark.asyncio
    async def test_destination_pie_sums_compute_bess_charge_grid_export(self) -> None:
        # Arrange — compute 800 kW/2h, BESS charges -500 kW/2h, grid exports -100/2h.
        start = datetime(2026, 5, 1, tzinfo=UTC)
        dtm = _dtm(
            {
                "compute_module_01": "compute_module",
                "bess_module_01": "bess_module",
                "revenue_meter_01": "revenue_meter",
            }
        )
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
        fake = _FakeServer(series)

        # Act
        art = await build_energy_breakdown(
            cast(ServerClient, fake),
            dtm,
            "demo-site",
            timedelta(hours=2),
            "destination",
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
        # Arrange — DTM has the devices but server returns no series
        dtm = _dtm({"bess_module_01": "bess_module"})
        fake = _FakeServer({})

        # Act
        art = await build_energy_breakdown(
            cast(ServerClient, fake), dtm, "demo-site", timedelta(hours=2), "source"
        )

        # Assert
        assert art.kind == "error"
