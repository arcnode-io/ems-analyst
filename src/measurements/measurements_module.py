"""Wires MeasurementsService → MeasurementsController for AppModule."""

from .measurements_controller import MeasurementsController
from .measurements_service import MeasurementsService


class MeasurementsModule:
    """Construct the /sites/{id}/measurements router with its service."""

    def __init__(self) -> None:
        """Service reads TIMESERIES_URL lazily per-request — no env at init."""
        self.router = MeasurementsController(MeasurementsService()).router
