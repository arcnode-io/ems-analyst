"""Wires ForecastsService → ForecastsController for AppModule."""

from ems_analyst_agent.config import load_config

from .forecasts_controller import ForecastsController
from .forecasts_service import ForecastsService


class ForecastsModule:
    """Construct the /forecast router with its service.

    Deploy site_id + settlement_point both come from the agent cfg
    (`site_id`, `market.settlement_point`) — single source of truth.
    Forecasts are hub-keyed; the response echoes the site.
    """

    def __init__(self) -> None:
        """Service reads TIMESERIES_URL lazily; site + hub from cfg."""
        config = load_config()
        self.router = ForecastsController(
            ForecastsService(),
            site_id=config.site_id,
            settlement_point=str(config.market.settlement_point),
        ).router
