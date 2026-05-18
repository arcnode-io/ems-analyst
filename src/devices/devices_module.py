"""Wires DevicesService → DevicesController for AppModule."""

from .devices_controller import DevicesController
from .devices_service import DevicesService


class DevicesModule:
    """Construct the /sites/{id}/devices router with its service."""

    def __init__(self) -> None:
        """Service reads TIMESERIES_URL lazily per-request — no env at init."""
        self.router = DevicesController(DevicesService()).router
