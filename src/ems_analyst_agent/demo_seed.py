"""Demo-mode bootstrap — seed public.measurements from bundled CSV.

When ENV=demo, the analyst-server calls seed_measurements() at startup
so the LLM has real (if synthetic) site data to query — agent reads it
through server's /sites/{id}/measurements endpoint, same path the HMI
uses. Idempotent: skips if the table already has rows.

CSV columns: ts, site_id, device_id, measurement, unit, value
- ts: ISO 8601 UTC ('Z' suffix)
- value: raw JSON literal (numbers unquoted, strings as "x" — Postgres COPY
  parses the CSV field into the JSONB column verbatim)

The CSV is bundled in the wheel via package-data in pyproject.toml.
"""

import io
import logging
from importlib import resources

import asyncpg

log = logging.getLogger(__name__)

_PKG_DATA: str = "ems_analyst_agent.demo_data"
_CSV_NAME: str = "measurements.csv"


async def seed_measurements(postgres_url: str) -> int:
    """Create the measurements table if absent and COPY the demo CSV into it.

    Returns the number of rows after seeding. Returns 0 (skip) if the table
    already has data so a restarted demo container doesn't keep stacking.
    """
    conn = await asyncpg.connect(postgres_url)
    try:
        # Schema MUST stay byte-for-byte aligned with platform-api's
        # telemetry_writer.py SCHEMA_SQL (every column NOT NULL incl. unit),
        # so the demo seed loads cleanly into a bootstrapped real DB if
        # someone ever runs ENV=demo against a shared backend by mistake.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS measurements (
                ts          TIMESTAMPTZ NOT NULL,
                site_id     TEXT        NOT NULL,
                device_id   TEXT        NOT NULL,
                measurement TEXT        NOT NULL,
                unit        TEXT        NOT NULL,
                value       JSONB       NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_measurements_lookup
                ON measurements (site_id, device_id, measurement, ts DESC);
        """)
        existing = await conn.fetchval("SELECT count(*) FROM public.measurements")
        if existing and existing > 0:
            log.info("demo seed skipped: %d rows already present", existing)
            return int(existing)
        csv_bytes = resources.files(_PKG_DATA).joinpath(_CSV_NAME).read_bytes()
        # asyncpg's COPY ... FROM STDIN takes an async source.
        await conn.copy_to_table(
            "measurements",
            source=io.BytesIO(csv_bytes),
            format="csv",
            header=True,
        )
        seeded = await conn.fetchval("SELECT count(*) FROM public.measurements")
        log.info("demo seed loaded %d rows into public.measurements", seeded)
        return int(seeded)
    finally:
        await conn.close()
