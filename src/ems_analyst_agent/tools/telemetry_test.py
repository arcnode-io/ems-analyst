"""Unit tests for telemetry builders — pure functions, no RunContext, no DB.

Real-builder tests against a real Postgres live in
tests/test_timeseries.py (testcontainer).
"""

from datetime import timedelta

from ..schemas import BarSpec, PieSpec
from .telemetry import (
    _parse_window,
    build_energy_breakdown_stub,
    build_markets_stub,
)


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
