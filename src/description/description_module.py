"""Wires DescriptionService → DescriptionController for AppModule."""

from .description_controller import DescriptionController
from .description_service import DescriptionService


class DescriptionModule:
    """Construct the /sites/{id}/description router with its service.

    `service` override lets AppModule inject the ENV=demo CSV-backed
    DemoData instead of the real Postgres-backed service.
    """

    def __init__(self, service: DescriptionService | None = None) -> None:
        """Default service reads TIMESERIES_URL lazily per-request."""
        self.router = DescriptionController(service or DescriptionService()).router
