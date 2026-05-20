"""Wires DevicesService → DevicesController for AppModule."""

from ems_analyst_agent.config import load_config

from .devices_controller import DevicesController
from .devices_service import DevicesService


class DevicesModule:
    """Construct the /devices router with its service.

    `service` override lets AppModule inject the ENV=demo CSV-backed
    DemoData. Deploy site_id comes from the agent cfg.
    """

    def __init__(self, service: DevicesService | None = None) -> None:
        """Default service reads TIMESERIES_URL lazily per-request."""
        site_id = load_config().site_id
        self.router = DevicesController(
            service or DevicesService(), site_id=site_id
        ).router
