"""GET /description — inventory of (device, measurement) pairs.

Single-site deploy: site_id comes from cfg, not the path.
"""

from classy_fastapi import Routable, get

from .description_service import DescriptionService
from .dto import SiteDescription


class DescriptionController(Routable):
    """Routes the inventory query through to DescriptionService."""

    def __init__(self, service: DescriptionService, site_id: str) -> None:
        super().__init__()
        self.service = service
        self.site_id = site_id

    @get(
        "/description",
        response_model=SiteDescription,
        tags=["Description"],
        responses={200: {"description": "Inventory of published data at the site"}},
    )
    async def describe(self) -> SiteDescription:
        """Return distinct (device, measurement) pairs + sample counts."""
        return await self.service.describe(site_id=self.site_id)
