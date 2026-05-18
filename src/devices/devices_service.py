"""asyncpg-backed device inventory + latest-status read.

Replaces the agent's TimeseriesClient.list_devices. Distinct device_ids
at the site, joined to the latest `status` measurement per device.
Status values come back JSONB-quoted ('"ok"'); strip for prose use.
"""

import logging
import os

import asyncpg

from .dto import DeviceList, DeviceRow

log = logging.getLogger(__name__)

_TIMESERIES_URL_ENV: str = "TIMESERIES_URL"


def _strip_quotes(jsonb_text: str | None) -> str | None:
    """jsonb text strings come back quoted; strip for prose use."""
    if jsonb_text is None:
        return None
    s = str(jsonb_text)
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s


class DevicesService:
    """Distinct devices at a site with their latest status (if any)."""

    def __init__(self, postgres_url: str | None = None) -> None:
        self._postgres_url = postgres_url

    async def list(self, site_id: str, status: list[str] | None = None) -> DeviceList:
        """Return distinct devices; optional status filter narrows the list.

        Devices that have never published a `status` measurement come
        back with status=None. The status filter excludes them.
        """
        url = self._postgres_url or os.environ[_TIMESERIES_URL_ENV]
        sql = """
            WITH latest_status AS (
                SELECT DISTINCT ON (device_id)
                       device_id, (value::text) AS status
                FROM measurements
                WHERE site_id = $1 AND measurement = 'status'
                ORDER BY device_id, ts DESC
            )
            SELECT DISTINCT m.device_id, ls.status
            FROM measurements m
            LEFT JOIN latest_status ls ON ls.device_id = m.device_id
            WHERE m.site_id = $1
            ORDER BY m.device_id
        """
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch(sql, site_id)
        finally:
            await conn.close()
        devices = [
            DeviceRow(
                device_id=str(r["device_id"]),
                status=_strip_quotes(r["status"]),
            )
            for r in rows
        ]
        if status:
            devices = [d for d in devices if d.status in status]
        return DeviceList(site_id=site_id, devices=devices)
