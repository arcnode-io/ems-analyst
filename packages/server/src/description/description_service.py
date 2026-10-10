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

from src.db import connect

from .dto import MeasurementPair, SiteDescription

log = logging.getLogger(__name__)

_TIMESERIES_URL_ENV: str = "TIMESERIES_URL"


class DescriptionService:
    """Inventory of distinct (device, measurement) pairs at a site."""

    def __init__(self, postgres_url: str | None = None) -> None:
        self._postgres_url = postgres_url

    async def describe(self, site_id: str) -> SiteDescription:
        """Return distinct (device, measurement) pairs queryable at the site.

        `GROUP BY device_id, measurement` (or even bare `DISTINCT`) scans
        the whole table: confirmed live against a real single-site
        deployment that `site_id = $1` alone has near-zero selectivity
        (nearly every row matches, since there's only one site), so
        Postgres can't use it to narrow the scan — 34s against ~58M rows,
        timing out the agent's 15s HTTP budget. A recursive-CTE index
        skip-scan over `idx_measurements_lookup (site_id, device_id,
        measurement, ts DESC)` instead walks directly from one distinct
        (device_id, measurement) pair to the next via the B-tree — O(distinct
        pairs), not O(rows). Confirmed live: ~290ms for 4,401 pairs.

        This used to also return a per-pair sample count via a correlated
        `COUNT(*)` subquery, but that count is itself unbounded — O(rows in
        that series), run once per pair — and reintroduced the same
        O(table size) blowup this query exists to avoid (confirmed live:
        100s+ and climbing as telemetry accumulates). The count was
        display-only (a "Samples" column), so it's dropped rather than
        bounded or cached — see system_adr.md for anything that changes
        this back.
        """
        url = self._postgres_url or os.environ[_TIMESERIES_URL_ENV]
        sql = """
            WITH RECURSIVE pairs AS (
                (SELECT device_id, measurement FROM measurements
                 WHERE site_id = $1
                 ORDER BY device_id, measurement LIMIT 1)
                UNION ALL
                SELECT nxt.device_id, nxt.measurement
                FROM pairs,
                LATERAL (
                    SELECT device_id, measurement FROM measurements
                    WHERE site_id = $1
                      AND (device_id, measurement) > (pairs.device_id, pairs.measurement)
                    ORDER BY device_id, measurement LIMIT 1
                ) nxt
            )
            SELECT pairs.device_id, pairs.measurement
            FROM pairs
            ORDER BY pairs.device_id, pairs.measurement
        """
        async with connect(url) as conn:
            rows = await conn.fetch(sql, site_id)
        pairs = [
            MeasurementPair(device_id=str(r["device_id"]), measurement=str(r["measurement"]))
            for r in rows
        ]
        return SiteDescription(site_id=site_id, pairs=pairs)
