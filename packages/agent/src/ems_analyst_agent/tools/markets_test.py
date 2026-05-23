"""Unit tests for markets.py — business logic only.

Full-stack HTTP integration lives in `tests/test_integration.py` per
[[feedback-test-taxonomy]].
"""

import os

import pytest

from .markets import _format, get_market_data


class TestFormat:
    """AAA tests for the JSON-envelope → text-summary helper."""

    def test_empty_rows(self) -> None:
        # Arrange
        payload: dict[str, list[object]] = {"data": []}

        # Act
        actual = _format("ercot_fuel_mix", payload)

        # Assert
        assert actual == "ercot_fuel_mix: no rows returned."

    def test_truncates_at_five(self) -> None:
        # Arrange
        payload = {"data": [{"i": n} for n in range(7)]}

        # Act
        actual = _format("d", payload)

        # Assert
        assert "7 row(s)" in actual
        assert "+2 more rows" in actual

    def test_renders_first_rows(self) -> None:
        # Arrange
        payload = {"data": [{"wind": 12345.6, "solar": 7890.1}]}

        # Act
        actual = _format("ercot_fuel_mix", payload)

        # Assert
        assert "wind=12345.6" in actual
        assert "solar=7890.1" in actual


class TestApiKeyGuard:
    """Env-var guard is pure logic — no network needed."""

    @pytest.mark.asyncio
    async def test_missing_api_key_raises(self) -> None:
        # Arrange
        os.environ.pop("GRIDSTATUS_API_KEY", None)

        # Act + Assert
        with pytest.raises(ValueError, match="GRIDSTATUS_API_KEY"):
            await get_market_data(dataset="ercot_fuel_mix")
