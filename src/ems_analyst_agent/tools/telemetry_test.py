"""Unit tests for telemetry builders — pure functions, no RunContext.

The RunContext-aware tool wrappers are exercised by tests/test_integration.py.
"""

from ..schemas import BarSpec, LineSpec, PieSpec, TableSpec, ToolError
from .telemetry import (
    build_device_list,
    build_energy_breakdown,
    build_markets,
    build_timeseries,
)


class TestBuildTimeseries:
    def test_known_device_returns_line_artifact(self) -> None:
        # Arrange + Act
        art = build_timeseries("BESS-01", "state_of_charge", "PT24H")

        # Assert
        assert art.kind == "line"
        assert isinstance(art.spec, LineSpec)
        assert art.spec.series[0].label == "BESS-01"
        assert len(art.spec.series[0].points) == 24

    def test_unknown_device_returns_error_artifact(self) -> None:
        # Arrange + Act
        art = build_timeseries("DOES-NOT-EXIST", "soc")

        # Assert
        assert art.kind == "error"
        assert isinstance(art.spec, ToolError)
        assert art.spec.code == "not_found"


class TestBuildDeviceList:
    def test_filters_by_status(self) -> None:
        # Arrange + Act
        art = build_device_list(status=["alarm"])

        # Assert
        assert art.kind == "table"
        assert isinstance(art.spec, TableSpec)
        assert len(art.spec.rows) == 1
        assert art.spec.rows[0]["device"] == "BESS-01"

    def test_no_filter_returns_all(self) -> None:
        # Arrange + Act
        art = build_device_list()

        # Assert
        assert isinstance(art.spec, TableSpec)
        assert len(art.spec.rows) == 3


class TestBuildMarkets:
    def test_returns_bar_artifact(self) -> None:
        # Arrange + Act
        art = build_markets(window="today")

        # Assert
        assert art.kind == "bar"
        assert isinstance(art.spec, BarSpec)
        assert "today" in art.spec.title


class TestBuildEnergyBreakdown:
    def test_returns_pie_artifact(self) -> None:
        # Arrange + Act
        art = build_energy_breakdown(window="today", by="source")

        # Assert
        assert art.kind == "pie"
        assert isinstance(art.spec, PieSpec)
        assert len(art.spec.slices) == 3
