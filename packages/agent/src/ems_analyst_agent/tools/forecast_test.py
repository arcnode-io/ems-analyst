"""Unit tests for build_forecast — shapes a LineSpec from ForecastSeries."""

from datetime import UTC, datetime, timedelta

import pytest

from ..schemas import LineSpec
from ..server_client import ForecastPoint, ForecastSeries
from .forecast import build_forecast


class _FakeServerClient:
    """Returns a canned forecast; records calls."""

    def __init__(self, series: ForecastSeries) -> None:
        self._series = series
        self.calls: list[dict[str, object]] = []

    async def get_forecast(self, **kwargs: object) -> ForecastSeries:
        self.calls.append(kwargs)
        return self._series


class TestBuildForecast:
    """AAA — build_forecast renders a line chart from server forecast points."""

    @pytest.mark.asyncio
    async def test_renders_line_chart_with_model_metadata(self) -> None:
        # Arrange
        ts = datetime(2026, 5, 18, 1, tzinfo=UTC)
        series = ForecastSeries(
            site_id="HB_NORTH",
            measurement="dam_lmp_price",
            unit="usd_per_mwh",
            model_name="dam-lmp-forecast",
            model_version=3,
            points=[
                ForecastPoint(forecast_for=ts, value=38.2),
                ForecastPoint(forecast_for=ts + timedelta(hours=1), value=41.7),
            ],
        )
        fake = _FakeServerClient(series=series)

        # Act
        art = await build_forecast(
            fake,  # ty: ignore[invalid-argument-type]
            measurement="dam_lmp_price",
            window=timedelta(hours=24),
        )

        # Assert
        assert art.kind == "line"
        assert isinstance(art.spec, LineSpec)
        assert "dam_lmp_price" in art.spec.title
        # Model lineage surfaced in the chart title so the user knows
        # which model version produced the curve.
        assert "v3" in art.spec.title or "dam-lmp-forecast" in art.spec.title

    @pytest.mark.asyncio
    async def test_empty_points_returns_error_artifact(self) -> None:
        # Arrange
        series = ForecastSeries(
            site_id="HB_NORTH",
            measurement="dam_lmp_price",
            unit="",
            model_name="",
            model_version=0,
            points=[],
        )
        fake = _FakeServerClient(series=series)

        # Act
        art = await build_forecast(
            fake,  # ty: ignore[invalid-argument-type]
            measurement="dam_lmp_price",
            window=timedelta(hours=24),
        )

        # Assert
        assert art.kind == "error"
