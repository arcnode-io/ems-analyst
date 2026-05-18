"""Wires ForecastsService → ForecastsController for AppModule."""

from .forecasts_controller import ForecastsController
from .forecasts_service import ForecastsService


class ForecastsModule:
    """Construct the /sites/{id}/forecast router with its service."""

    def __init__(self) -> None:
        """Service reads TIMESERIES_URL lazily per-request — no env at init."""
        self.router = ForecastsController(ForecastsService()).router
