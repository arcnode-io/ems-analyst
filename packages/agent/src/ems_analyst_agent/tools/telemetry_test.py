"""Unit tests for telemetry builders — pure functions over a fake ServerClient.

ServerClient HTTP behaviour itself is pook-tested in
tests/test_server_client.py; these tests exercise the artifact-shaping
logic in build_timeseries + build_site_description.
"""

from datetime import UTC, datetime, timedelta

import pytest

from ..schemas import LineSpec, TableSpec
from ..server_client import (
    MeasurementPair,
    MeasurementPoint,
    MeasurementSeries,
    SiteDescription,
)
from ._common import _parse_window
from .telemetry import build_site_description, build_timeseries


class _FakeServerClient:
    """Returns canned ServerClient responses; records calls."""

    def __init__(
        self,
        measurements: MeasurementSeries | None = None,
        description: SiteDescription | None = None,
    ) -> None:
        self._measurements = measurements
        self._description = description
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def get_measurements(self, **kwargs: object) -> MeasurementSeries:
        self.calls.append(("get_measurements", kwargs))
        assert self._measurements is not None
        return self._measurements

    async def describe_site(self) -> SiteDescription:
        self.calls.append(("describe_site", {}))
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
            device_id="BESS-01",
            measurement="power_kw",
            window=timedelta(hours=1),
            aggregation="mean",
        )

        # Assert
        assert art.kind == "error"


class TestBuildSiteDescription:
    """AAA — build_site_description shapes a TableSpec from the inventory."""

    @pytest.mark.asyncio
    async def test_renders_inventory_table(self) -> None:
        # Arrange — incl. a non-device market series
        desc = SiteDescription(
            site_id="demo-site",
            pairs=[
                MeasurementPair(
                    device_id="market_01",
                    measurement="dam_clearing_price_usd_per_mwh",
                    samples=712,
                ),
                MeasurementPair(
                    device_id="bess_module_01",
                    measurement="state_of_charge",
                    samples=712,
                ),
            ],
        )
        fake = _FakeServerClient(description=desc)

        # Act
        art = await build_site_description(fake)  # ty: ignore[invalid-argument-type]

        # Assert
        assert art.kind == "table"
        assert isinstance(art.spec, TableSpec)
        assert len(art.spec.rows) == 2

    @pytest.mark.asyncio
    async def test_empty_inventory_returns_error_artifact(self) -> None:
        # Arrange
        fake = _FakeServerClient(
            description=SiteDescription(site_id="demo-site", pairs=[])
        )

        # Act
        art = await build_site_description(fake)  # ty: ignore[invalid-argument-type]

        # Assert
        assert art.kind == "error"
