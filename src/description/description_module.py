"""Wires DescriptionService → DescriptionController for AppModule."""

from ems_analyst_agent.config import load_config

from .description_controller import DescriptionController
from .description_service import DescriptionService


class DescriptionModule:
    """Construct the /description router with its service.

    `service` override lets AppModule inject the ENV=demo CSV-backed
    DemoData. Deploy site_id comes from the agent cfg.
    """

    def __init__(self, service: DescriptionService | None = None) -> None:
        """Default service reads TIMESERIES_URL lazily per-request."""
        site_id = load_config().site_id
        self.router = DescriptionController(
            service or DescriptionService(), site_id=site_id
        ).router
