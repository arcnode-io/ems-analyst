"""Wires MeasurementsService → MeasurementsController for AppModule."""

from ems_analyst_agent.config import load_config

from .measurements_controller import MeasurementsController
from .measurements_service import MeasurementsService


class MeasurementsModule:
    """Construct the /measurements router with its service.

    `service` override lets AppModule inject the ENV=demo CSV-backed
    DemoData. The deploy site_id comes from the agent cfg — single
    source of truth, single-site deploy.
    """

    def __init__(self, service: MeasurementsService | None = None) -> None:
        """Default service reads TIMESERIES_URL lazily per-request."""
        site_id = load_config().site_id
        self.router = MeasurementsController(
            service or MeasurementsService(), site_id=site_id
        ).router
