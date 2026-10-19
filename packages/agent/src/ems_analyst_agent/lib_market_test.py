"""Market prompt line — present only when the deploy has a market."""

from .config import ErcotMarket, ErcotSettlementPoint
from .lib import market_context


def test_market_context_names_the_hub_when_enrolled() -> None:
    """Enrolled deploy: the prompt names the ISO and settlement point."""
    # Arrange
    market = ErcotMarket(
        wholesale_market="ercot", settlement_point=ErcotSettlementPoint.HB_NORTH
    )

    # Act
    text = market_context(market)

    # Assert
    assert "ERCOT" in text
    assert "HB_NORTH" in text


def test_market_context_is_empty_when_not_enrolled() -> None:
    """No market: no hub line, so the model never assumes one."""
    # Arrange
    market = None

    # Act
    text = market_context(market)

    # Assert
    assert text == ""
