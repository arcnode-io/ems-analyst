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
        """Return (device, measurement, sample_count) rows for the site.

        `GROUP BY device_id, measurement` (or even bare `DISTINCT`) scans
        the whole table: confirmed live against a real single-site
        deployment that `site_id = $1` alone has near-zero selectivity
        (nearly every row matches, since there's only one site), so
        Postgres can't use it to narrow the scan — 34s against ~58M rows,
        timing out the agent's 15s HTTP budget. A recursive-CTE index
        skip-scan over `idx_measurements_lookup (site_id, device_id,
        measurement, ts DESC)` instead walks directly from one distinct
        (device_id, measurement) pair to the next via the B-tree, then a
        per-pair COUNT(*) is a cheap bounded index-range scan (just that
        series' rows, not the table). Confirmed live: 7.8s for the same
        4,401 pairs with full counts — same result, same portable plain
        SQL (no TimescaleDB-only functions — this also runs on the
        Aurora + pg_partman defense variant per system_adr.md §7).
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
            SELECT
                pairs.device_id,
                pairs.measurement,
                (SELECT COUNT(*) FROM measurements m
                 WHERE m.site_id = $1
                   AND m.device_id = pairs.device_id
                   AND m.measurement = pairs.measurement) AS samples
            FROM pairs
            ORDER BY pairs.device_id, pairs.measurement
        """
        async with connect(url) as conn:
            rows = await conn.fetch(sql, site_id)
        pairs = [
            MeasurementPair(
                device_id=str(r["device_id"]),
                measurement=str(r["measurement"]),
                samples=int(r["samples"]),
            )
            for r in rows
        ]
        return SiteDescription(site_id=site_id, pairs=pairs)
