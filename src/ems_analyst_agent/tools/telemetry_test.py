"""Unit tests for telemetry builders — pure functions over a fake ServerClient.

ServerClient HTTP behaviour itself is pook-tested in
tests/test_server_client.py; these tests exercise the artifact-shaping
logic in build_timeseries / build_site_description / build_device_list.
"""

from datetime import UTC, datetime, timedelta

import pytest

from ..schemas import BarSpec, LineSpec, PieSpec, TableSpec
from ..server_client import (
    DeviceList,
    DeviceRow,
    MeasurementPair,
    MeasurementPoint,
    MeasurementSeries,
    SiteDescription,
)
from .telemetry import (
    _parse_window,
    build_device_list,
    build_energy_breakdown_stub,
    build_markets_stub,
    build_site_description,
    build_timeseries,
)


class _FakeServerClient:
    """Returns canned ServerClient responses; records calls."""

    def __init__(
        self,
        measurements: MeasurementSeries | None = None,
        devices: DeviceList | None = None,
        description: SiteDescription | None = None,
    ) -> None:
        self._measurements = measurements
        self._devices = devices
        self._description = description
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def get_measurements(self, **kwargs: object) -> MeasurementSeries:
        self.calls.append(("get_measurements", kwargs))
        assert self._measurements is not None
        return self._measurements

    async def list_devices(self, **kwargs: object) -> DeviceList:
        self.calls.append(("list_devices", kwargs))
        assert self._devices is not None
        return self._devices

    async def describe_site(self, **kwargs: object) -> SiteDescription:
        self.calls.append(("describe_site", kwargs))
        assert self._description is not None
        return self._description


class TestParseWindow:
    def test_iso_hours(self) -> None:
        assert _parse_window("PT24H") == timedelta(hours=24)

    def test_iso_minutes(self) -> None:
        assert _parse_window("PT30M") == timedelta(minutes=30)

    def test_shorthand_hours(self) -> None:
        assert _parse_window("1h") == timedelta(hours=1)

    def test_shorthand_days(self) -> None:
        assert _parse_window("7d") == timedelta(days=7)

    def test_unknown_defaults_to_24h(self) -> None:
        assert _parse_window("bogus") == timedelta(hours=24)


class TestBuildMarketsStub:
    def test_chart_title_carries_placeholder_label(self) -> None:
        # Arrange + Act
        art = build_markets_stub()

        # Assert — placeholder label baked in so LLM conveys uncertainty
        assert art.kind == "bar"
        assert isinstance(art.spec, BarSpec)
        assert "PLACEHOLDER" in art.spec.title

    def test_returns_zero_valued_series(self) -> None:
        # Arrange + Act
        art = build_markets_stub()

        # Assert
        assert isinstance(art.spec, BarSpec)
        assert art.spec.series[0].values == [0.0, 0.0, 0.0]


class TestBuildEnergyBreakdownStub:
    def test_chart_title_carries_placeholder_label(self) -> None:
        # Arrange + Act
        art = build_energy_breakdown_stub()

        # Assert
        assert art.kind == "pie"
        assert isinstance(art.spec, PieSpec)
        assert "PLACEHOLDER" in art.spec.title

    def test_returns_single_zero_slice(self) -> None:
        # Arrange + Act
        art = build_energy_breakdown_stub()

        # Assert
        assert isinstance(art.spec, PieSpec)
        assert len(art.spec.slices) == 1
        assert art.spec.slices[0].value == 0.0


class TestBuildTimeseries:
    """AAA — build_timeseries shapes a LineSpec from MeasurementSeries."""

    @pytest.mark.asyncio
    async def test_renders_line_chart_from_server_points(self) -> None:
        # Arrange
        ts = datetime(2026, 5, 18, 1, tzinfo=UTC)
        series = MeasurementSeries(
            site_id="site-A",
            device_id="BESS-01",
            measurement="power_kw",
            unit="kw",
            points=[
                MeasurementPoint(ts=ts, value=42.5),
                MeasurementPoint(ts=ts + timedelta(hours=1), value=None),
            ],
        )
        fake = _FakeServerClient(measurements=series)

        # Act
        art = await build_timeseries(
            fake,  # ty: ignore[invalid-argument-type]
            site_id="site-A",
            device_id="BESS-01",
            measurement="power_kw",
            window=timedelta(hours=2),
            aggregation="mean",
        )

        # Assert
        assert art.kind == "line"
        assert isinstance(art.spec, LineSpec)
        assert "BESS-01 power_kw" in art.spec.title

    @pytest.mark.asyncio
    async def test_empty_points_returns_error_artifact(self) -> None:
        # Arrange
        series = MeasurementSeries(
            site_id="site-A",
            device_id="BESS-01",
            measurement="power_kw",
            unit="",
            points=[],
        )
        fake = _FakeServerClient(measurements=series)

        # Act
        art = await build_timeseries(
            fake,  # ty: ignore[invalid-argument-type]
            site_id="site-A",
            device_id="BESS-01",
            measurement="power_kw",
            window=timedelta(hours=1),
            aggregation="mean",
        )

        # Assert
        assert art.kind == "error"


class TestBuildSiteDescription:
    """AAA — shapes a TableSpec from SiteDescription."""

    @pytest.mark.asyncio
    async def test_renders_table_from_pairs(self) -> None:
        # Arrange
        desc = SiteDescription(
            site_id="site-E",
            pairs=[
                MeasurementPair(device_id="BESS-01", measurement="soc", samples=24),
            ],
        )
        fake = _FakeServerClient(description=desc)

        # Act
        art = await build_site_description(
            fake,  # ty: ignore[invalid-argument-type]
            site_id="site-E",
        )

        # Assert
        assert art.kind == "table"
        assert isinstance(art.spec, TableSpec)
        assert len(art.spec.rows) == 1

    @pytest.mark.asyncio
    async def test_empty_pairs_returns_error_artifact(self) -> None:
        # Arrange
        desc = SiteDescription(site_id="site-nope", pairs=[])
        fake = _FakeServerClient(description=desc)

        # Act
        art = await build_site_description(
            fake,  # ty: ignore[invalid-argument-type]
            site_id="site-nope",
        )

        # Assert
        assert art.kind == "error"


class TestBuildDeviceList:
    """AAA — shapes a TableSpec from DeviceList; optional status filter."""

    @pytest.mark.asyncio
    async def test_renders_table_with_status_severity(self) -> None:
        # Arrange
        devs = DeviceList(
            site_id="site-D",
            devices=[
                DeviceRow(device_id="BESS-01", status="ok"),
                DeviceRow(device_id="INV-02", status=None),
            ],
        )
        fake = _FakeServerClient(devices=devs)

        # Act
        art = await build_device_list(
            fake,  # ty: ignore[invalid-argument-type]
            site_id="site-D",
            status=None,
        )

        # Assert
        assert art.kind == "table"
        assert isinstance(art.spec, TableSpec)
        assert len(art.spec.rows) == 2
