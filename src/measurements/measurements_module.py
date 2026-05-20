"""Wires MeasurementsService → MeasurementsController for AppModule."""

from .measurements_controller import MeasurementsController
from .measurements_service import MeasurementsService


class MeasurementsModule:
    """Construct the /sites/{id}/measurements router with its service.

    `service` override lets AppModule inject the ENV=demo CSV-backed
    DemoData instead of the real Postgres-backed service.
    """

    def __init__(self, service: MeasurementsService | None = None) -> None:
        """Default service reads TIMESERIES_URL lazily per-request."""
        self.router = MeasurementsController(service or MeasurementsService()).router
