"""Unit tests for build_explain_dispatch — two time-aligned line artifacts.

The money-math correctness itself is covered by dispatch_explain_test.py
(compute_dispatch_stats, pure); these tests just check the fetch → shape
wiring and the empty-data error path.
"""

from datetime import UTC, datetime, timedelta

import pytest

from ..schemas import LineSpec
from ..server_client import MeasurementPoint, MeasurementSeries
from .dispatch_explain_artifact import build_explain_dispatch

_T0 = datetime(2026, 1, 1, 0, tzinfo=UTC)


def _series(device_id: str, measurement: str, values: list[float]) -> MeasurementSeries:
    return MeasurementSeries(
        site_id="demo-site",
        device_id=device_id,
        measurement=measurement,
        unit="",
        points=[
            MeasurementPoint(ts=_T0 + timedelta(hours=i), value=v)
            for i, v in enumerate(values)
        ],
    )


class _FakeServerClient:
    """Keyed by (device_id, measurement) — build_explain_dispatch fetches 5 series."""

    def __init__(self, series_by_key: dict[tuple[str, str], MeasurementSeries]) -> None:
        self._series = series_by_key

    async def get_measurements(self, **kwargs: object) -> MeasurementSeries:
        key = (str(kwargs["device_id"]), str(kwargs["measurement"]))
        return self._series[key]


class TestBuildExplainDispatch:
    """AAA — fetch → compute_dispatch_stats → two line artifacts."""

    @pytest.mark.asyncio
    async def test_renders_price_and_dispatch_charts(self) -> None:
        # Arrange
        fake = _FakeServerClient(
            {
                ("market_01", "dam_clearing_price_usd_per_mwh"): _series(
                    "market_01", "dam_clearing_price_usd_per_mwh", [40, 41, 190]
                ),
                ("market_01", "rtm_clearing_price_usd_per_mwh"): _series(
                    "market_01", "rtm_clearing_price_usd_per_mwh", [40, 41, 190]
                ),
                ("bess_module_01", "dam_dispatch_w"): _series(
                    "bess_module_01", "dam_dispatch_w", [0, 0, 1_500_000]
                ),
                ("bess_module_01", "rtm_dispatch_w"): _series(
                    "bess_module_01", "rtm_dispatch_w", [0, 0, 0]
                ),
                ("bess_module_01", "state_of_charge"): _series(
                    "bess_module_01", "state_of_charge", [80, 78, 70]
                ),
            }
        )

        # Act
        artifacts, stats = await build_explain_dispatch(
            fake,  # ty: ignore[invalid-argument-type]
            "bess_module_01",
            timedelta(hours=3),
        )

        # Assert — price chart, then dispatch chart, both line kind
        assert len(artifacts) == 2
        assert artifacts[0].kind == "line"
        assert artifacts[1].kind == "line"
        assert isinstance(artifacts[0].spec, LineSpec)
        assert isinstance(artifacts[1].spec, LineSpec)
        assert "DAM clearing price" in artifacts[0].spec.title
        assert "bess_module_01 net dispatch" in artifacts[1].spec.title
        assert stats is not None
        assert stats.discharge_hours == 1

    @pytest.mark.asyncio
    async def test_no_price_data_returns_error_artifact(self) -> None:
        # Arrange — dam price series present but empty
        fake = _FakeServerClient(
            {
                ("market_01", "dam_clearing_price_usd_per_mwh"): _series(
                    "market_01", "dam_clearing_price_usd_per_mwh", []
                ),
            }
        )

        # Act
        artifacts, stats = await build_explain_dispatch(
            fake,  # ty: ignore[invalid-argument-type]
            "bess_module_01",
            timedelta(hours=3),
        )

        # Assert
        assert len(artifacts) == 1
        assert artifacts[0].kind == "error"
        assert stats is None
