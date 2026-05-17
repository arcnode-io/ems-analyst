"""Tests for the gridstatus.io market data tool."""

import os
from unittest.mock import patch

import pook
import pytest

from .markets import GRIDSTATUS_BASE_URL, get_market_data


@pytest.fixture(autouse=True)
def _api_key() -> None:
    """Inject a dummy key so the empty-key guard does not trip."""
    os.environ["GRIDSTATUS_API_KEY"] = "test-key"


class TestGetMarketData:
    """AAA tests for the gridstatus.io REST wrapper."""

    @pytest.mark.asyncio
    async def test_missing_api_key_raises(self) -> None:
        """Empty GRIDSTATUS_API_KEY → ValueError, fail fast."""
        # Arrange
        os.environ.pop("GRIDSTATUS_API_KEY", None)

        # Reason: re-import not required — the function reads env at call time.
        from .markets import get_market_data as fresh

        # Act + Assert
        with pytest.raises(ValueError, match="GRIDSTATUS_API_KEY"):
            with patch.dict(os.environ, {"GRIDSTATUS_API_KEY": ""}, clear=False):
                await fresh(dataset="ercot_fuel_mix")

    @pytest.mark.asyncio
    async def test_successful_query_returns_summary(self) -> None:
        """Happy path: pook-mocked 200 → human-readable summary string."""
        # Arrange
        pook.on()
        pook.enable_network()
        pook.get(f"{GRIDSTATUS_BASE_URL}/datasets/ercot_fuel_mix/query").reply(200).json(
            {
                "data": [
                    {
                        "interval_start_utc": "2026-05-16T00:00:00Z",
                        "wind": 12345.6,
                        "solar": 7890.1,
                        "natural_gas": 30000.0,
                    }
                ],
                "meta": {"hasNextPage": False},
            }
        )

        try:
            # Act
            actual = await get_market_data(dataset="ercot_fuel_mix", limit=1)

            # Assert
            assert "ercot_fuel_mix" in actual
            assert "wind" in actual.lower() or "natural_gas" in actual.lower()
        finally:
            pook.off()

    @pytest.mark.asyncio
    async def test_401_returns_friendly_message(self) -> None:
        """Bad key → user-facing message instead of httpx exception."""
        # Arrange
        pook.on()
        pook.enable_network()
        pook.get(
            f"{GRIDSTATUS_BASE_URL}/datasets/ercot_fuel_mix/query"
        ).reply(401).json({"error": "Invalid API key"})

        try:
            # Act
            actual = await get_market_data(dataset="ercot_fuel_mix")

            # Assert
            assert "api_key" in actual.lower() or "401" in actual
        finally:
            pook.off()
