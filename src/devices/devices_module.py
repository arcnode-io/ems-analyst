"""Wires DevicesService → DevicesController for AppModule."""

from .devices_controller import DevicesController
from .devices_service import DevicesService


class DevicesModule:
    """Construct the /sites/{id}/devices router with its service.

    `service` override lets AppModule inject the ENV=demo CSV-backed
    DemoData instead of the real Postgres-backed service.
    """

    def __init__(self, service: DevicesService | None = None) -> None:
        """Default service reads TIMESERIES_URL lazily per-request."""
        self.router = DevicesController(service or DevicesService()).router
