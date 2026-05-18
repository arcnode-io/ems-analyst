"""GET /sites/{site_id}/devices — distinct devices + latest status."""

from typing import Annotated

from classy_fastapi import Routable, get
from fastapi import Query

from .devices_service import DevicesService
from .dto import DeviceList


class DevicesController(Routable):
    """Routes a device-inventory query through to DevicesService."""

    def __init__(self, service: DevicesService) -> None:
        super().__init__()
        self.service = service

    @get(
        "/sites/{site_id}/devices",
        response_model=DeviceList,
        tags=["Devices"],
        responses={200: {"description": "Distinct devices at the site"}},
    )
    async def list_devices(
        self,
        site_id: str,
        status: Annotated[list[str] | None, Query()] = None,
    ) -> DeviceList:
        """Return the device list — optional status filter narrows it."""
        return await self.service.list(site_id=site_id, status=status)
