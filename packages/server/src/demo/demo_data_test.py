"""Unit tests for DemoData — CSV-backed mock for ENV=demo.

Pure: reads the bundled CSV from the ems-analyst-agent package, no DB.
Asserts `get` and `describe` return correctly-shaped DTOs.
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.demo.demo_data import DemoData

_SITE: str = "demo-site"


@pytest.fixture(scope="module")
def demo() -> DemoData:
    """Parse the bundled demo CSV once for the module."""
    return DemoData()


class TestDemoDataMeasurements:
    @pytest.mark.asyncio
    async def test_get_recent_window_has_points(self, demo: DemoData) -> None:
        # Arrange — CSV time-shifted so max(ts) == now; last 6h has data
        end = datetime.now(UTC)
        start = end - timedelta(hours=6)

        # Act
        actual = await demo.get(
            site_id=_SITE,
            device_id="bess_module_01",
            measurement="active_power",
            start=start,
            end=end,
        )

        # Assert — hourly buckets, at least one real value
        assert actual.device_id == "bess_module_01"
        assert len(actual.points) >= 6
        assert any(p.value is not None for p in actual.points)

    @pytest.mark.asyncio
    async def test_get_far_past_window_all_gap_filled(self, demo: DemoData) -> None:
        # Arrange — window before any CSV data
        start = datetime(1999, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=3)

        # Act
        actual = await demo.get(
            site_id=_SITE,
            device_id="bess_module_01",
            measurement="active_power",
            start=start,
            end=end,
        )

        # Assert — buckets present, all None
        assert all(p.value is None for p in actual.points)

    @pytest.mark.asyncio
    async def test_get_categorical_status_value_not_coerced_to_float(
        self, demo: DemoData
    ) -> None:
        # Arrange — status is an enum (ok/warn/alarm), not a numeric series
        start = datetime(2000, 1, 1, tzinfo=UTC)
        end = datetime.now(UTC) + timedelta(days=1)

        # Act
        actual = await demo.get(
            site_id=_SITE,
            device_id="cdu_01",
            measurement="status",
            start=start,
            end=end,
            aggregation="last",
        )

        # Assert — the string value survives; no float() coercion crash
        values = [p.value for p in actual.points if p.value is not None]
        assert values == ["alarm"]


class TestDemoDataGetLatest:
    @pytest.mark.asyncio
    async def test_get_latest_returns_most_recent_per_pair(
        self, demo: DemoData
    ) -> None:
        # Act
        actual = await demo.get_latest(
            site_id=_SITE,
            device_ids=["cdu_01", "bess_module_01"],
            measurements=["status", "active_power"],
        )

        # Assert — only pairs that actually exist in the CSV come back
        pairs = {(v.device_id, v.measurement): v.value for v in actual}
        assert pairs[("cdu_01", "status")] == "alarm"
        assert ("bess_module_01", "active_power") in pairs
        assert ("cdu_01", "active_power") not in pairs

    @pytest.mark.asyncio
    async def test_get_latest_unknown_pair_omitted(self, demo: DemoData) -> None:
        # Act
        actual = await demo.get_latest(
            site_id=_SITE,
            device_ids=["no-such-device"],
            measurements=["no-such-measurement"],
        )

        # Assert
        assert actual == []


class TestDemoDataDescribe:
    @pytest.mark.asyncio
    async def test_describe_includes_market_price_series(self, demo: DemoData) -> None:
        # Act
        actual = await demo.describe(_SITE)

        # Assert — the non-device market series is discoverable here even
        # though it has no DTM device (the reason /description exists)
        pairs = {(p.device_id, p.measurement) for p in actual.pairs}
        assert ("market_01", "dam_clearing_price_usd_per_mwh") in pairs
        assert ("bess_module_01", "state_of_charge") in pairs

    @pytest.mark.asyncio
    async def test_describe_unknown_site_empty(self, demo: DemoData) -> None:
        # Act
        actual = await demo.describe("no-such-site")

        # Assert
        assert actual.pairs == []
