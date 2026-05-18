"""DTOs for /sites/{id}/description responses."""

from pydantic import BaseModel


class MeasurementPair(BaseModel):
    """One (device, measurement) pair + how many samples have landed."""

    device_id: str
    measurement: str
    samples: int


class SiteDescription(BaseModel):
    """Inventory of what's actually published at a site — discovery payload."""

    site_id: str
    pairs: list[MeasurementPair]
