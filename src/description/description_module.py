"""Wires DescriptionService → DescriptionController for AppModule."""

from .description_controller import DescriptionController
from .description_service import DescriptionService


class DescriptionModule:
    """Construct the /sites/{id}/description router with its service."""

    def __init__(self) -> None:
        """Service reads TIMESERIES_URL lazily per-request — no env at init."""
        self.router = DescriptionController(DescriptionService()).router
