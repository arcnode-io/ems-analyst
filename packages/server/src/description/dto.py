"""DTOs for GET /description responses."""

from pydantic import BaseModel


class MeasurementPair(BaseModel):
    """One (device, measurement) pair that's queryable at the site."""

    device_id: str
    measurement: str


class SiteDescription(BaseModel):
    """Inventory of what's actually published at a site — discovery payload."""

    site_id: str
    pairs: list[MeasurementPair]
