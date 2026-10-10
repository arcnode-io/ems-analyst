"""Unit tests for build_compare_forecast — one overlaid line chart.

Accuracy-math correctness is covered by forecast_accuracy_test.py
(compute_forecast_accuracy, pure); these tests just check the
fetch -> align -> shape wiring and the empty-data error paths.
"""

from datetime import UTC, datetime, timedelta

import pytest

from ..schemas import LineSpec
from ..server_client import (
    ForecastPoint,
    ForecastSeries,
    MeasurementPoint,
    MeasurementSeries,
)
from .compare_forecast_artifact import build_compare_forecast

_T0 = datetime(2026, 1, 1, 0, tzinfo=UTC)


def _forecast(values: list[float]) -> ForecastSeries:
    return ForecastSeries(
        site_id="demo-site",
        measurement="dam_lmp_price",
        unit="usd_per_mwh",
        model_name="demo-seed",
        model_version=0,
        points=[
            ForecastPoint(forecast_for=_T0 + timedelta(hours=i), value=v)
            for i, v in enumerate(values)
        ],
    )


def _actual(values: list[float]) -> MeasurementSeries:
    return MeasurementSeries(
        site_id="demo-site",
        device_id="market_01",
        measurement="dam_clearing_price_usd_per_mwh",
        unit="usd_per_mwh",
        points=[
            MeasurementPoint(ts=_T0 + timedelta(hours=i), value=v)
            for i, v in enumerate(values)
        ],
    )


class _FakeServerClient:
    def __init__(
        self, forecast: ForecastSeries, actual: MeasurementSeries | None = None
    ) -> None:
        self._forecast = forecast
        self._actual = actual

    async def get_forecast(self, **_kwargs: object) -> ForecastSeries:
        return self._forecast

    async def get_measurements(self, **_kwargs: object) -> MeasurementSeries:
        assert self._actual is not None
        return self._actual


class TestBuildCompareForecast:
    """AAA — fetch both series -> align by hour -> one overlaid line chart."""

    @pytest.mark.asyncio
    async def test_renders_overlaid_chart_with_bias_in_note(self) -> None:
        # Arrange — forecast [30,32,34,36], actual [31,30,40,36] (errors +1,-2,+6,0)
        fake = _FakeServerClient(
            forecast=_forecast([30, 32, 34, 36]), actual=_actual([31, 30, 40, 36])
        )

        # Act
        artifacts, stats = await build_compare_forecast(
            fake,  # ty: ignore[invalid-argument-type]
            timedelta(hours=4),
        )

        # Assert
        assert len(artifacts) == 1
        assert artifacts[0].kind == "line"
        spec = artifacts[0].spec
        assert isinstance(spec, LineSpec)
        assert [s.label for s in spec.series] == ["forecast", "actual"]
        assert len(spec.series[0].points) == 4
        assert stats is not None
        assert stats.mean_bias == 1.25
        assert stats.mae == 2.25

    @pytest.mark.asyncio
    async def test_empty_forecast_returns_error_artifact(self) -> None:
        # Arrange — no forecast rows published for this window
        fake = _FakeServerClient(forecast=_forecast([]))

        # Act
        artifacts, stats = await build_compare_forecast(
            fake,  # ty: ignore[invalid-argument-type]
            timedelta(hours=4),
        )

        # Assert
        assert len(artifacts) == 1
        assert artifacts[0].kind == "error"
        assert stats is None

    @pytest.mark.asyncio
    async def test_no_overlapping_hours_returns_error_artifact(self) -> None:
        # Arrange — forecast and actual cover disjoint hours
        forecast = _forecast([30, 32])
        actual = MeasurementSeries(
            site_id="demo-site",
            device_id="market_01",
            measurement="dam_clearing_price_usd_per_mwh",
            unit="usd_per_mwh",
            points=[MeasurementPoint(ts=_T0 + timedelta(hours=100), value=50.0)],
        )
        fake = _FakeServerClient(forecast=forecast, actual=actual)

        # Act
        artifacts, stats = await build_compare_forecast(
            fake,  # ty: ignore[invalid-argument-type]
            timedelta(hours=4),
        )

        # Assert
        assert len(artifacts) == 1
        assert artifacts[0].kind == "error"
        assert stats is None
