"""Wires ForecastsService → ForecastsController for AppModule."""

from ems_analyst_agent.config import load_config

from .forecasts_controller import ForecastsController
from .forecasts_service import ForecastsService


class ForecastsModule:
    """Construct the /sites/{id}/forecast router with its service.

    The deploy's settlement_point comes from the agent's cfg
    (`market.settlement_point`) — single source of truth, already
    carries that field per stage. Forecasts are hub-keyed; the
    controller maps the requested site → this hub.
    """

    def __init__(self) -> None:
        """Service reads TIMESERIES_URL lazily; settlement_point from cfg."""
        settlement_point = load_config().market.settlement_point
        self.router = ForecastsController(
            ForecastsService(), settlement_point=str(settlement_point)
        ).router
