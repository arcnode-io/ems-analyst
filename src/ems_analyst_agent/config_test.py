"""Loader tests — customer-merge + market discriminated-union typing."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ems_analyst_agent.config import (
    ErcotSettlementPoint,
    _deep_merge,
    load_config,
)


def test_load_config_returns_baked_defaults_without_customer_file() -> None:
    """Local stage in cfg.defaults.yml: ERCOT + HB_NORTH dev defaults."""
    # Arrange
    env = {k: v for k, v in os.environ.items() if k != "CFG_CUSTOMER_PATH"}
    env["ENV"] = "local"
    with patch.dict(os.environ, env, clear=True):
        # Act
        cfg = load_config()

    # Assert
    assert cfg.market.wholesale_market == "ercot"
    assert cfg.market.settlement_point == ErcotSettlementPoint.HB_NORTH


def test_load_config_customer_merges_market_block(tmp_path: Path) -> None:
    """cfg.customer.yml at CFG_CUSTOMER_PATH wins over baked defaults."""
    # Arrange
    customer = tmp_path / "cfg.customer.yml"
    customer.write_text(
        "market:\n"
        "  wholesale_market: ercot\n"
        "  settlement_point: HB_HOUSTON\n"
    )
    with patch.dict(
        os.environ, {"ENV": "local", "CFG_CUSTOMER_PATH": str(customer)}, clear=False
    ):
        # Act
        cfg = load_config()

    # Assert — customer wins
    assert cfg.market.settlement_point == ErcotSettlementPoint.HB_HOUSTON
    # Provider settings untouched (customer only mentioned market)
    assert cfg.settings.llm_provider == "ollama"


def test_load_config_rejects_unknown_settlement_point(tmp_path: Path) -> None:
    """Discriminated union catches typos at load time."""
    # Arrange
    customer = tmp_path / "cfg.customer.yml"
    customer.write_text(
        "market:\n"
        "  wholesale_market: ercot\n"
        "  settlement_point: HB_TYPO\n"
    )

    # Act / Assert
    with patch.dict(
        os.environ, {"ENV": "local", "CFG_CUSTOMER_PATH": str(customer)}, clear=False
    ):
        with pytest.raises(Exception, match=r"HB_TYPO"):
            load_config()


def test_load_config_ignores_missing_customer_file(tmp_path: Path) -> None:
    """CFG_CUSTOMER_PATH pointing at a nonexistent file = no merge, no error."""
    # Arrange
    missing = tmp_path / "does-not-exist.yml"
    with patch.dict(
        os.environ, {"ENV": "local", "CFG_CUSTOMER_PATH": str(missing)}, clear=False
    ):
        # Act
        cfg = load_config()

    # Assert
    assert cfg.market.settlement_point == ErcotSettlementPoint.HB_NORTH


def test_deep_merge_overlays_nested_dicts() -> None:
    """Sanity check — nested dicts merge, scalars overwrite."""
    # Arrange
    base = {"a": {"x": 1, "y": 2}, "b": "base"}
    customer = {"a": {"y": 20, "z": 3}, "b": "customer"}

    # Act
    merged = _deep_merge(base, customer)

    # Assert
    assert merged == {"a": {"x": 1, "y": 20, "z": 3}, "b": "customer"}
