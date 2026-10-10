"""Unit tests for market_prices.py — typed gridstatus.io series fetch.

fetch_market_series is the structured counterpart to markets.py's
get_market_data (LLM text): compare_forecast_to_actual needs real
numbers to do arithmetic with, not a formatted string.
"""

import os
from datetime import UTC, datetime

import pook
import pytest

from .market_prices import GRIDSTATUS_BASE_URL, MarketPricePoint, _InvalidApiKeyError, fetch_market_series

_DATASET = "ercot_spp_day_ahead_hourly"
_START = datetime(2026, 7, 15, 0, tzinfo=UTC)
_END = datetime(2026, 7, 15, 23, tzinfo=UTC)
_QUERY_URL = f"{GRIDSTATUS_BASE_URL}/datasets/{_DATASET}/query"


class TestFetchMarketSeries:
    """AAA — same HTTP + fallback behavior as get_market_data, typed output."""

    def setup_method(self) -> None:
        os.environ["GRIDSTATUS_API_KEY"] = "fake-key-for-tests"
        pook.on()

    def teardown_method(self) -> None:
        pook.off()
        pook.reset()

    @pytest.mark.asyncio
    async def test_parses_real_rows_by_column_name(self) -> None:
        # Arrange
        pook.get(_QUERY_URL).reply(200).json(
            {
                "data": [
                    {
                        "interval_start_utc": "2026-07-15T00:00:00Z",
                        "spp": 30.5,
                        "location": "HB_NORTH",
                    },
                    {
                        "interval_start_utc": "2026-07-15T01:00:00Z",
                        "spp": 31.2,
                        "location": "HB_NORTH",
                    },
                ]
            }
        )

        # Act
        actual = await fetch_market_series(
            dataset=_DATASET,
            location="HB_NORTH",
            ts_column="interval_start_utc",
            value_column="spp",
            start=_START,
            end=_END,
            limit=25,
        )

        # Assert
        assert actual == [
            MarketPricePoint(ts=datetime(2026, 7, 15, 0, tzinfo=UTC), value=30.5),
            MarketPricePoint(ts=datetime(2026, 7, 15, 1, tzinfo=UTC), value=31.2),
        ]

    @pytest.mark.asyncio
    async def test_quota_exhausted_falls_back_to_synthetic_hourly_series(self) -> None:
        # Arrange — 403 means quota's out, not "no data available"
        pook.get(_QUERY_URL).reply(403)

        # Act
        actual = await fetch_market_series(
            dataset=_DATASET,
            location="HB_NORTH",
            ts_column="interval_start_utc",
            value_column="spp",
            start=_START,
            end=_END,
            limit=25,
        )

        # Assert — one point per hour across the window, all flagged synthetic
        assert len(actual) == 24
        assert all(p.is_synthetic for p in actual)
        assert actual[-1].ts == _END

    @pytest.mark.asyncio
    async def test_synthetic_fallback_deterministic_for_same_window(self) -> None:
        # Arrange — same seed inputs on both calls, no flapping on retry
        pook.get(_QUERY_URL).times(2).reply(429)

        # Act
        first = await fetch_market_series(
            dataset=_DATASET,
            location="HB_NORTH",
            ts_column="interval_start_utc",
            value_column="spp",
            start=_START,
            end=_END,
            limit=25,
        )
        second = await fetch_market_series(
            dataset=_DATASET,
            location="HB_NORTH",
            ts_column="interval_start_utc",
            value_column="spp",
            start=_START,
            end=_END,
            limit=25,
        )

        # Assert
        assert first == second

    @pytest.mark.asyncio
    async def test_invalid_key_raises(self) -> None:
        # Arrange — 401 is a real config problem, not a fallback trigger
        pook.get(_QUERY_URL).reply(401)

        # Act + Assert
        with pytest.raises(_InvalidApiKeyError):
            await fetch_market_series(
                dataset=_DATASET,
                location="HB_NORTH",
                ts_column="interval_start_utc",
                value_column="spp",
                start=_START,
                end=_END,
                limit=25,
            )

    @pytest.mark.asyncio
    async def test_missing_api_key_raises_value_error(self) -> None:
        # Arrange
        os.environ.pop("GRIDSTATUS_API_KEY", None)

        # Act + Assert
        with pytest.raises(ValueError, match="GRIDSTATUS_API_KEY"):
            await fetch_market_series(
                dataset=_DATASET,
                location="HB_NORTH",
                ts_column="interval_start_utc",
                value_column="spp",
                start=_START,
                end=_END,
                limit=25,
            )
