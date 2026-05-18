"""GET /sites/{site_id}/description — inventory of (device, measurement) pairs."""

from classy_fastapi import Routable, get

from .description_service import DescriptionService
from .dto import SiteDescription


class DescriptionController(Routable):
    """Routes the inventory query through to DescriptionService."""

    def __init__(self, service: DescriptionService) -> None:
        super().__init__()
        self.service = service

    @get(
        "/sites/{site_id}/description",
        response_model=SiteDescription,
        tags=["Description"],
        responses={200: {"description": "Inventory of published data at the site"}},
    )
    async def describe(self, site_id: str) -> SiteDescription:
        """Return distinct (device, measurement) pairs + sample counts."""
        return await self.service.describe(site_id=site_id)
