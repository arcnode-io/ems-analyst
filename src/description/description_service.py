"""asyncpg-backed site inventory read.

The historian-side discovery surface: every (device, measurement) pair
actually present in the measurements table, with a sample count. The
agent calls this to learn exact measurement names before querying.

Distinct from the DTM (ems-device-api): the DTM describes installed
*equipment*; this describes *queryable series* — which includes
non-device series like market price feeds, and the names that really
landed (templates can drift from the historian).
"""

import logging
import os

import asyncpg

from .dto import MeasurementPair, SiteDescription

log = logging.getLogger(__name__)

_TIMESERIES_URL_ENV: str = "TIMESERIES_URL"


class DescriptionService:
    """Inventory of distinct (device, measurement) pairs at a site."""

    def __init__(self, postgres_url: str | None = None) -> None:
        self._postgres_url = postgres_url

    async def describe(self, site_id: str) -> SiteDescription:
        """Return (device, measurement, sample_count) rows for the site."""
        url = self._postgres_url or os.environ[_TIMESERIES_URL_ENV]
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch(
                "SELECT device_id, measurement, COUNT(*) AS samples "
                "FROM measurements WHERE site_id = $1 "
                "GROUP BY device_id, measurement "
                "ORDER BY device_id, measurement",
                site_id,
            )
        finally:
            await conn.close()
        pairs = [
            MeasurementPair(
                device_id=str(r["device_id"]),
                measurement=str(r["measurement"]),
                samples=int(r["samples"]),
            )
            for r in rows
        ]
        return SiteDescription(site_id=site_id, pairs=pairs)
