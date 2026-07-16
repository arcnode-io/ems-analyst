"""Unit tests for markets.py — business logic only.

Full-stack HTTP integration lives in `tests/test_integration.py` per
[[feedback-test-taxonomy]].
"""

import os
from datetime import UTC, datetime

import pook
import pytest

from .markets import (
    GRIDSTATUS_BASE_URL,
    _format,
    _synthetic_fallback,
    get_market_data,
)

# Pinned anchor time keeps determinism tests stable across hour boundaries.
_FIXED_NOW: datetime = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


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


class TestSyntheticFallbackHelper:
    """Direct tests of the fallback generator — no HTTP needed."""

    def test_marker_present(self) -> None:
        # Arrange + Act
        actual = _synthetic_fallback("ercot_lmp", None, None, 5, 403, now=_FIXED_NOW)

        # Assert
        assert "SYNTHETIC DATA" in actual
        assert "gridstatus HTTP 403" in actual
        assert "ercot_lmp" in actual

    def test_deterministic_for_same_inputs(self) -> None:
        # Arrange + Act
        first = _synthetic_fallback(
            "ercot_lmp", "2026-01-01", "2026-01-02", 5, 403, now=_FIXED_NOW
        )
        second = _synthetic_fallback(
            "ercot_lmp", "2026-01-01", "2026-01-02", 5, 403, now=_FIXED_NOW
        )

        # Assert — same seed + same anchor → identical string.
        assert first == second

    def test_limit_capped_at_five(self) -> None:
        # Arrange + Act
        actual = _synthetic_fallback("ercot_lmp", None, None, 100, 429, now=_FIXED_NOW)

        # Assert — output uses "5 row(s)" wording from _format.
        assert "5 row(s)" in actual

    def test_status_echoed_in_header(self) -> None:
        # Arrange + Act
        for status in (403, 404, 429):
            actual = _synthetic_fallback("d", None, None, 3, status, now=_FIXED_NOW)
            # Assert
            assert f"HTTP {status}" in actual


class TestHttpStatusMapping:
    """End-to-end: httpx mocked with pook, assert branch selection."""

    def setup_method(self) -> None:
        os.environ["GRIDSTATUS_API_KEY"] = "fake-key-for-tests"
        pook.on()

    def teardown_method(self) -> None:
        pook.off()
        pook.reset()

    @pytest.mark.asyncio
    async def test_403_returns_synthetic(self) -> None:
        # Arrange
        pook.get(f"{GRIDSTATUS_BASE_URL}/datasets/ercot_lmp/query").reply(403)

        # Act
        actual = await get_market_data(dataset="ercot_lmp")

        # Assert
        assert "SYNTHETIC DATA" in actual
        assert "HTTP 403" in actual

    @pytest.mark.asyncio
    async def test_404_returns_synthetic(self) -> None:
        # Arrange
        pook.get(f"{GRIDSTATUS_BASE_URL}/datasets/made_up/query").reply(404)

        # Act
        actual = await get_market_data(dataset="made_up")

        # Assert
        assert "SYNTHETIC DATA" in actual
        assert "HTTP 404" in actual

    @pytest.mark.asyncio
    async def test_429_returns_synthetic(self) -> None:
        # Arrange
        pook.get(f"{GRIDSTATUS_BASE_URL}/datasets/x/query").reply(429)

        # Act
        actual = await get_market_data(dataset="x")

        # Assert
        assert "SYNTHETIC DATA" in actual

    @pytest.mark.asyncio
    async def test_401_returns_key_error_not_synthetic(self) -> None:
        # Arrange
        pook.get(f"{GRIDSTATUS_BASE_URL}/datasets/x/query").reply(401)

        # Act
        actual = await get_market_data(dataset="x")

        # Assert — 401 must NOT synthesise; it's a config problem to surface.
        assert "SYNTHETIC" not in actual
        assert "GRIDSTATUS_API_KEY" in actual

    @pytest.mark.asyncio
    async def test_500_returns_error_not_synthetic(self) -> None:
        # Arrange
        pook.get(f"{GRIDSTATUS_BASE_URL}/datasets/x/query").reply(500)

        # Act
        actual = await get_market_data(dataset="x")

        # Assert — server error is not the same as "quota out".
        assert "SYNTHETIC" not in actual
        assert "HTTP 500" in actual

    @pytest.mark.asyncio
    async def test_200_passes_through_real_data(self) -> None:
        # Arrange
        pook.get(f"{GRIDSTATUS_BASE_URL}/datasets/ercot_fuel_mix/query").reply(
            200
        ).json({"data": [{"wind": 100.0, "solar": 50.0}]})

        # Act
        actual = await get_market_data(dataset="ercot_fuel_mix")

        # Assert — real path renders normally, no synthetic marker.
        assert "SYNTHETIC" not in actual
        assert "wind=100.0" in actual
