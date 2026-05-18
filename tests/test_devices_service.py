"""Integration tests for DevicesService against a real Postgres.

Replaces TimeseriesClient.list_devices — distinct device_ids at the
site, each with its latest 'status' measurement (None if never reported).
Optional status filter narrows the list.
"""

import json
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from src.devices.devices_service import DevicesService


@pytest.fixture(scope="session")
def postgres_url() -> Generator[str]:
    with PostgresContainer(
        "postgres:15", username="postgres", password="testpw", dbname="postgres"
    ) as pg:
        port = int(pg.get_exposed_port(5432))
        yield f"postgres://postgres:testpw@localhost:{port}/postgres"


@pytest_asyncio.fixture
async def devices_service(postgres_url: str) -> DevicesService:
    return DevicesService(postgres_url=postgres_url)


async def _seed_measurements_table(postgres_url: str) -> None:
    conn = await asyncpg.connect(postgres_url)
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS measurements (
                ts          TIMESTAMPTZ,
                site_id     TEXT,
                device_id   TEXT,
                measurement TEXT,
                unit        TEXT,
                value       JSONB
            )
        """)
    finally:
        await conn.close()


async def _insert(
    postgres_url: str,
    ts: datetime,
    site_id: str,
    device_id: str,
    measurement: str,
    value: object,
) -> None:
    conn = await asyncpg.connect(postgres_url)
    try:
        await conn.execute(
            "INSERT INTO measurements "
            "(ts, site_id, device_id, measurement, unit, value) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            ts,
            site_id,
            device_id,
            measurement,
            "",
            json.dumps(value),
        )
    finally:
        await conn.close()


class TestDevicesService:
    """AAA — distinct devices with their latest status."""

    @pytest.mark.asyncio
    async def test_lists_distinct_devices_with_status(
        self, postgres_url: str, devices_service: DevicesService
    ) -> None:
        # Arrange — seed two devices with status, one with only power_kw
        await _seed_measurements_table(postgres_url)
        now = datetime.now(UTC).replace(microsecond=0)
        await _insert(postgres_url, now, "site-D", "BESS-01", "status", "ok")
        await _insert(
            postgres_url,
            now - timedelta(hours=1),
            "site-D",
            "BESS-02",
            "status",
            "warn",
        )
        await _insert(postgres_url, now, "site-D", "BESS-02", "status", "alarm")
        await _insert(postgres_url, now, "site-D", "INV-03", "power_kw", 12.0)

        # Act
        actual = await devices_service.list(site_id="site-D")

        # Assert — 3 devices, latest status per device, INV-03 has None
        by_dev = {d.device_id: d for d in actual.devices}
        assert by_dev["BESS-01"].status == "ok"
        assert by_dev["BESS-02"].status == "alarm"
        assert by_dev["INV-03"].status is None

    @pytest.mark.asyncio
    async def test_filter_excludes_devices_without_status_when_filter_given(
        self, devices_service: DevicesService
    ) -> None:
        # Act — filter to alarm only
        actual = await devices_service.list(site_id="site-D", status=["alarm"])

        # Assert
        devs = [d.device_id for d in actual.devices]
        assert devs == ["BESS-02"]
