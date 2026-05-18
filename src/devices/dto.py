"""DTOs for /sites/{id}/devices responses."""

from pydantic import BaseModel


class DeviceRow(BaseModel):
    """One device + its latest 'status' measurement (None if never reported)."""

    device_id: str
    status: str | None


class DeviceList(BaseModel):
    """Response envelope — distinct devices at a site."""

    site_id: str
    devices: list[DeviceRow]
