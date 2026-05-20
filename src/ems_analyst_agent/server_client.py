"""HTTP client over ems-analyst-server's deterministic REST endpoints.

Principle: the agent is just another client of server, same as HMI. All
historian + forecast reads route through these four endpoints rather
than touching Postgres directly.

DTOs mirror server's response shapes — defined here to avoid a cycle
(server imports the agent for /chat).
"""

import logging
import os
from datetime import datetime
from typing import Final, Literal

import httpx
from pydantic import BaseModel

log = logging.getLogger(__name__)

_SERVER_URL_ENV: Final[str] = "SERVER_URL"
_HTTP_TIMEOUT: Final[float] = 15.0

Aggregation = Literal["mean", "max", "min", "last"]


class MeasurementPoint(BaseModel):
    """One bucketed point — value=None for empty buckets."""

    ts: datetime
    value: float | None


class MeasurementSeries(BaseModel):
    """Bucketed series for one (site, device, measurement)."""

    site_id: str
    device_id: str
    measurement: str
    unit: str
    points: list[MeasurementPoint]


class DeviceRow(BaseModel):
    """One device + its latest status (None if never reported)."""

    device_id: str
    status: str | None


class DeviceList(BaseModel):
    """Distinct devices at a site."""

    site_id: str
    devices: list[DeviceRow]


class MeasurementPair(BaseModel):
    """One (device, measurement) pair + sample count at the site."""

    device_id: str
    measurement: str
    samples: int


class SiteDescription(BaseModel):
    """Inventory of what's published at a site."""

    site_id: str
    pairs: list[MeasurementPair]


class ForecastPoint(BaseModel):
    """One (forecast_for, value) prediction."""

    forecast_for: datetime
    value: float


class ForecastSeries(BaseModel):
    """Forecast points for one (site, measurement) from a registered model."""

    site_id: str
    measurement: str
    unit: str
    model_name: str
    model_version: int
    points: list[ForecastPoint]


def _iso_z(ts: datetime) -> str:
    """ISO 8601 UTC with a `Z` suffix — never `+00:00`.

    The whole arcnode stack is ISO UTC. The `+` in `+00:00` decodes to
    a space in a URL query string → FastAPI rejects it as a malformed
    datetime. The `Z` form has no `+`, so it survives URL transport.
    """
    return ts.isoformat().replace("+00:00", "Z")


class ServerClient:
    """REST client for the four server data endpoints."""

    def __init__(self, base_url: str | None = None) -> None:
        """Optional URL override for tests; production reads SERVER_URL."""
        self.base_url = (base_url or os.environ[_SERVER_URL_ENV]).rstrip("/")

    async def get_measurements(
        self,
        device_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
        aggregation: Aggregation = "mean",
    ) -> MeasurementSeries:
        """GET /measurements — hourly-bucketed gap-filled series.

        Single-site deploy: the server knows its own site_id, no site
        in the URL.
        """
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as c:
            resp = await c.get(
                f"{self.base_url}/measurements",
                params={
                    "device_id": device_id,
                    "measurement": measurement,
                    "start": _iso_z(start),
                    "end": _iso_z(end),
                    "aggregation": aggregation,
                },
            )
            resp.raise_for_status()
        return MeasurementSeries.model_validate(resp.json())

    async def list_devices(self, status: list[str] | None = None) -> DeviceList:
        """GET /devices — distinct devices + latest status."""
        params: list[tuple[str, str | int | float | None]] = []
        if status:
            params.extend(("status", s) for s in status)
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as c:
            resp = await c.get(f"{self.base_url}/devices", params=params)
            resp.raise_for_status()
        return DeviceList.model_validate(resp.json())

    async def describe_site(self) -> SiteDescription:
        """GET /description — inventory of (device, measurement) pairs."""
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as c:
            resp = await c.get(f"{self.base_url}/description")
            resp.raise_for_status()
        return SiteDescription.model_validate(resp.json())

    async def get_forecast(
        self,
        measurement: str,
        start: datetime,
        end: datetime,
    ) -> ForecastSeries:
        """GET /forecast — model-published prediction points."""
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as c:
            resp = await c.get(
                f"{self.base_url}/forecast",
                params={
                    "measurement": measurement,
                    "start": _iso_z(start),
                    "end": _iso_z(end),
                },
            )
            resp.raise_for_status()
        return ForecastSeries.model_validate(resp.json())
