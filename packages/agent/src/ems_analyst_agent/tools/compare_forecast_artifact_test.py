"""Unit tests for build_compare_forecast — one overlaid line chart.

Accuracy-math correctness is covered by forecast_accuracy_test.py
(compute_forecast_accuracy, pure); these tests just check the
fetch -> align -> shape wiring and the empty-data error paths.

"Actual" comes from gridstatus.io (market_prices.fetch_market_series),
not a fake ServerClient method — mocked with pook the same way
markets_test.py mocks the real HTTP boundary, rather than adding a
mock-injection seam fetch_market_series doesn't otherwise need.
"""

import os
from datetime import UTC, datetime, timedelta

import pook
import pytest

from ..schemas import LineSpec
from ..server_client import ForecastPoint, ForecastSeries
from .compare_forecast_artifact import build_compare_forecast
from .market_prices import GRIDSTATUS_BASE_URL

_T0 = datetime(2026, 1, 1, 0, tzinfo=UTC)
_QUERY_URL = f"{GRIDSTATUS_BASE_URL}/datasets/ercot_spp_day_ahead_hourly/query"


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


def _actual_rows(values: list[float]) -> list[dict[str, object]]:
    return [
        {
            "interval_start_utc": (_T0 + timedelta(hours=i)).isoformat().replace(
                "+00:00", "Z"
            ),
            "spp": v,
            "location": "HB_NORTH",
        }
        for i, v in enumerate(values)
    ]


class _FakeServerClient:
    def __init__(self, forecast: ForecastSeries) -> None:
        self._forecast = forecast

    async def get_forecast(self, **_kwargs: object) -> ForecastSeries:
        return self._forecast


class TestBuildCompareForecast:
    """AAA — fetch both series -> align by hour -> one overlaid line chart."""

    def setup_method(self) -> None:
        os.environ["GRIDSTATUS_API_KEY"] = "fake-key-for-tests"
        pook.on()

    def teardown_method(self) -> None:
        pook.off()
        pook.reset()

    @pytest.mark.asyncio
    async def test_renders_overlaid_chart_with_bias_in_note(self) -> None:
        # Arrange — forecast [30,32,34,36], actual [31,30,40,36] (errors +1,-2,+6,0)
        fake = _FakeServerClient(forecast=_forecast([30, 32, 34, 36]))
        pook.get(_QUERY_URL).reply(200).json({"data": _actual_rows([31, 30, 40, 36])})

        # Act
        artifacts, stats, is_synthetic = await build_compare_forecast(
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
        assert is_synthetic is False

    @pytest.mark.asyncio
    async def test_empty_forecast_returns_error_artifact(self) -> None:
        # Arrange — no forecast rows published for this window
        fake = _FakeServerClient(forecast=_forecast([]))

        # Act
        artifacts, stats, is_synthetic = await build_compare_forecast(
            fake,  # ty: ignore[invalid-argument-type]
            timedelta(hours=4),
        )

        # Assert — forecast is empty before actual is ever fetched
        assert len(artifacts) == 1
        assert artifacts[0].kind == "error"
        assert stats is None
        assert is_synthetic is False

    @pytest.mark.asyncio
    async def test_no_overlapping_hours_returns_error_artifact(self) -> None:
        # Arrange — forecast and actual cover disjoint hours
        fake = _FakeServerClient(forecast=_forecast([30, 32]))
        far_row = [
            {
                "interval_start_utc": (_T0 + timedelta(hours=100))
                .isoformat()
                .replace("+00:00", "Z"),
                "spp": 50.0,
                "location": "HB_NORTH",
            }
        ]
        pook.get(_QUERY_URL).reply(200).json({"data": far_row})

        # Act
        artifacts, stats, is_synthetic = await build_compare_forecast(
            fake,  # ty: ignore[invalid-argument-type]
            timedelta(hours=4),
        )

        # Assert
        assert len(artifacts) == 1
        assert artifacts[0].kind == "error"
        assert stats is None
        assert is_synthetic is False

    @pytest.mark.asyncio
    async def test_gridstatus_unavailable_flags_synthetic_in_note(self) -> None:
        # Arrange — quota exhausted; synthetic fallback is anchored to the
        # real request window (unlike the mocked-response tests above), so
        # the forecast fixture has to line up with "now" too, not _T0.
        anchor = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        forecast = ForecastSeries(
            site_id="demo-site",
            measurement="dam_lmp_price",
            unit="usd_per_mwh",
            model_name="demo-seed",
            model_version=0,
            points=[
                ForecastPoint(forecast_for=anchor - timedelta(hours=i), value=30.0 + i)
                for i in range(4)
            ],
        )
        fake = _FakeServerClient(forecast=forecast)
        pook.get(_QUERY_URL).reply(403)

        # Act
        artifacts, stats, is_synthetic = await build_compare_forecast(
            fake,  # ty: ignore[invalid-argument-type]
            timedelta(hours=4),
        )

        # Assert
        assert is_synthetic is True
        assert stats is not None
        spec = artifacts[0].spec
        assert isinstance(spec, LineSpec)
        assert spec.note is not None
        assert "SYNTHETIC" in spec.note
