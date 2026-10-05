"""Integration tests for MeasurementsService against a real Postgres.

The agent + HMI both consume measurements via server's REST endpoints
(principle: agent is just another client of server). Service serves
hourly-bucketed, gap-filled timeseries per (site, device, measurement)
— same shape the agent's old TimeseriesClient.query_hourly returned.

Schema:
  measurements(ts timestamptz, site_id text, device_id text,
               measurement text, unit text, value jsonb)
"""

import json
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from src.measurements.measurements_service import MeasurementsService


@pytest.fixture(scope="session")
def postgres_url() -> Generator[str]:
    """Session-scoped Postgres testcontainer — reused across tests."""
    with PostgresContainer(
        "postgres:15", username="postgres", password="testpw", dbname="postgres"
    ) as pg:
        port = int(pg.get_exposed_port(5432))
        yield f"postgres://postgres:testpw@localhost:{port}/postgres"


@pytest_asyncio.fixture
async def measurements_service(postgres_url: str) -> MeasurementsService:
    """Fresh MeasurementsService — schema created lazily on first call."""
    return MeasurementsService(postgres_url=postgres_url)


async def _seed_measurements_table(postgres_url: str) -> None:
    """Create the canonical measurements table."""
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


async def _insert_measurement(
    postgres_url: str,
    ts: datetime,
    site_id: str,
    device_id: str,
    measurement: str,
    unit: str,
    value: float | str | bool,
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
            unit,
            json.dumps(value),
        )
    finally:
        await conn.close()


class TestMeasurementsService:
    """AAA — hourly-bucketed, gap-filled timeseries per (site, device, measurement)."""

    @pytest.mark.asyncio
    async def test_get_returns_bucketed_value_for_seeded_hour(
        self, postgres_url: str, measurements_service: MeasurementsService
    ) -> None:
        # Arrange — seed one point at the top of an hour, request a 2-hour window
        await _seed_measurements_table(postgres_url)
        bucket_ts = datetime.now(UTC).replace(minute=15, second=0, microsecond=0)
        await _insert_measurement(
            postgres_url,
            ts=bucket_ts,
            site_id="site-A",
            device_id="device-1",
            measurement="power_kw",
            unit="kw",
            value=42.5,
        )

        # Act — bucket=1h, agg=mean, window covers the seeded hour
        actual = await measurements_service.get(
            site_id="site-A",
            device_id="device-1",
            measurement="power_kw",
            start=bucket_ts.replace(minute=0),
            end=bucket_ts.replace(minute=0) + timedelta(hours=2),
            aggregation="mean",
        )

        # Assert — value bucketed under the hour, unit echoed
        assert actual.site_id == "site-A"
        assert actual.device_id == "device-1"
        assert actual.measurement == "power_kw"
        assert actual.unit == "kw"
        seeded_hour = bucket_ts.replace(minute=0)
        # at least one point matching the seeded hour with our value
        matching = [p for p in actual.points if p.ts == seeded_hour and p.value == 42.5]
        assert len(matching) == 1

    @pytest.mark.asyncio
    async def test_get_returns_none_value_for_missing_buckets(
        self, measurements_service: MeasurementsService
    ) -> None:
        # Arrange — window includes hours with no data → those buckets should
        # come back with value=None (gap-filled, not omitted).
        far_past = datetime(1999, 1, 1, tzinfo=UTC)

        # Act
        actual = await measurements_service.get(
            site_id="site-A",
            device_id="device-1",
            measurement="power_kw",
            start=far_past,
            end=far_past + timedelta(hours=3),
            aggregation="mean",
        )

        # Assert — every bucket present, every value None
        assert len(actual.points) >= 3
        assert all(p.value is None for p in actual.points)

    @pytest.mark.asyncio
    async def test_get_decodes_enum_string_value(
        self, postgres_url: str, measurements_service: MeasurementsService
    ) -> None:
        """A gateway-published enum label must come back as a real str.

        value JSONB column stores '"SW_POWER_CAP"' — the old
        `(value::text)::float` cast hard-crashes on this; it must decode
        to the Python str, not raise.
        """
        # Arrange
        await _seed_measurements_table(postgres_url)
        bucket_ts = datetime.now(UTC).replace(minute=20, second=0, microsecond=0)
        await _insert_measurement(
            postgres_url,
            ts=bucket_ts,
            site_id="site-B",
            device_id="gpu-1",
            measurement="throttle_reason",
            unit="",
            value="SW_POWER_CAP",
        )

        # Act
        actual = await measurements_service.get(
            site_id="site-B",
            device_id="gpu-1",
            measurement="throttle_reason",
            start=bucket_ts.replace(minute=0),
            end=bucket_ts.replace(minute=0) + timedelta(hours=1),
            aggregation="last",
        )

        # Assert
        matching = [p for p in actual.points if p.value is not None]
        assert len(matching) == 1
        assert matching[0].value == "SW_POWER_CAP"

    @pytest.mark.asyncio
    async def test_get_decodes_boolean_value(
        self, postgres_url: str, measurements_service: MeasurementsService
    ) -> None:
        """A gateway-published boolean must come back as a real Python bool."""
        # Arrange
        await _seed_measurements_table(postgres_url)
        bucket_ts = datetime.now(UTC).replace(minute=25, second=0, microsecond=0)
        await _insert_measurement(
            postgres_url,
            ts=bucket_ts,
            site_id="site-B",
            device_id="relay-1",
            measurement="breaker_closed",
            unit="",
            value=True,
        )

        # Act
        actual = await measurements_service.get(
            site_id="site-B",
            device_id="relay-1",
            measurement="breaker_closed",
            start=bucket_ts.replace(minute=0),
            end=bucket_ts.replace(minute=0) + timedelta(hours=1),
            aggregation="last",
        )

        # Assert
        matching = [p for p in actual.points if p.value is not None]
        assert len(matching) == 1
        assert matching[0].value is True

    @pytest.mark.asyncio
    async def test_get_mean_still_works_for_pure_numeric_bucket(
        self, postgres_url: str, measurements_service: MeasurementsService
    ) -> None:
        """Regression guard: numeric aggregation must survive the jsonb_typeof branch."""
        # Arrange — two numeric samples in the same hour bucket
        await _seed_measurements_table(postgres_url)
        bucket_ts = datetime.now(UTC).replace(minute=30, second=0, microsecond=0)
        await _insert_measurement(
            postgres_url,
            ts=bucket_ts,
            site_id="site-C",
            device_id="device-2",
            measurement="power_kw",
            unit="kw",
            value=10.0,
        )
        await _insert_measurement(
            postgres_url,
            ts=bucket_ts.replace(minute=45),
            site_id="site-C",
            device_id="device-2",
            measurement="power_kw",
            unit="kw",
            value=20.0,
        )

        # Act
        actual = await measurements_service.get(
            site_id="site-C",
            device_id="device-2",
            measurement="power_kw",
            start=bucket_ts.replace(minute=0),
            end=bucket_ts.replace(minute=0) + timedelta(hours=1),
            aggregation="mean",
        )

        # Assert
        matching = [p for p in actual.points if p.value is not None]
        assert len(matching) == 1
        assert matching[0].value == 15.0

    @pytest.mark.asyncio
    async def test_get_mixed_bucket_falls_back_to_latest_raw_value(
        self, postgres_url: str, measurements_service: MeasurementsService
    ) -> None:
        """A bucket mixing numeric + non-numeric values ignores the agg fn.

        Mirrors DemoData._agg's existing semantics: mean/max/min are
        meaningless once any reading in the bucket isn't a number, so the
        bucket falls back to its latest raw value regardless of the
        requested aggregation — never a crash, never a silently-wrong
        partial average.
        """
        # Arrange — a numeric sample followed by a categorical one, same hour
        await _seed_measurements_table(postgres_url)
        bucket_ts = datetime.now(UTC).replace(minute=10, second=0, microsecond=0)
        await _insert_measurement(
            postgres_url,
            ts=bucket_ts,
            site_id="site-D",
            device_id="device-3",
            measurement="mixed_measurement",
            unit="",
            value=5.0,
        )
        await _insert_measurement(
            postgres_url,
            ts=bucket_ts.replace(minute=40),
            site_id="site-D",
            device_id="device-3",
            measurement="mixed_measurement",
            unit="",
            value="NA",
        )

        # Act
        actual = await measurements_service.get(
            site_id="site-D",
            device_id="device-3",
            measurement="mixed_measurement",
            start=bucket_ts.replace(minute=0),
            end=bucket_ts.replace(minute=0) + timedelta(hours=1),
            aggregation="mean",
        )

        # Assert — latest raw value ("NA"), not a crash and not a numeric mean
        matching = [p for p in actual.points if p.value is not None]
        assert len(matching) == 1
        assert matching[0].value == "NA"

    @pytest.mark.asyncio
    async def test_get_bucket_s_defaults_to_hourly_unchanged(
        self, postgres_url: str, measurements_service: MeasurementsService
    ) -> None:
        """Regression guard: omitting bucket_s must behave exactly as before."""
        # Arrange
        await _seed_measurements_table(postgres_url)
        bucket_ts = datetime.now(UTC).replace(minute=12, second=0, microsecond=0)
        await _insert_measurement(
            postgres_url,
            ts=bucket_ts,
            site_id="site-E",
            device_id="device-4",
            measurement="power_kw",
            unit="kw",
            value=7.0,
        )

        # Act — no bucket_s passed
        actual = await measurements_service.get(
            site_id="site-E",
            device_id="device-4",
            measurement="power_kw",
            start=bucket_ts.replace(minute=0),
            end=bucket_ts.replace(minute=0) + timedelta(hours=1),
            aggregation="mean",
        )

        # Assert — hour-wide bucket boundaries, matching old date_trunc('hour', ...)
        # (generate_series is inclusive at both ends, so a 1h window yields 2
        # buckets: the seeded hour and the next boundary, gap-filled None)
        assert actual.points[0].ts == bucket_ts.replace(minute=0)
        assert actual.points[0].value == 7.0
        assert all(p.value is None for p in actual.points[1:])

    @pytest.mark.asyncio
    async def test_get_fine_bucket_s_separates_samples_within_the_hour(
        self, postgres_url: str, measurements_service: MeasurementsService
    ) -> None:
        """bucket_s=10 gives the HMI's power-balance chart minute-ish resolution.

        Two samples 20s apart, in the same hour, must land in two different
        10-second buckets rather than both collapsing into one hourly bucket.
        """
        # Arrange
        await _seed_measurements_table(postgres_url)
        base_ts = datetime.now(UTC).replace(minute=5, second=0, microsecond=0)
        await _insert_measurement(
            postgres_url,
            ts=base_ts,
            site_id="site-F",
            device_id="meter_01",
            measurement="active_power",
            unit="kw",
            value=100.0,
        )
        await _insert_measurement(
            postgres_url,
            ts=base_ts + timedelta(seconds=20),
            site_id="site-F",
            device_id="meter_01",
            measurement="active_power",
            unit="kw",
            value=200.0,
        )

        # Act
        actual = await measurements_service.get(
            site_id="site-F",
            device_id="meter_01",
            measurement="active_power",
            start=base_ts,
            end=base_ts + timedelta(seconds=30),
            aggregation="mean",
            bucket_s=10,
        )

        # Assert — 4 buckets of 10s spanning [base_ts, base_ts+30s]; the two
        # samples land in different buckets, each reported individually
        values = {p.ts: p.value for p in actual.points if p.value is not None}
        assert values == {base_ts: 100.0, base_ts + timedelta(seconds=20): 200.0}


class TestMeasurementsServiceGetLatest:
    """AAA — bulk latest-value lookup across many (device, measurement) pairs.

    Exists so a rollup over many devices (e.g. device-status across a
    whole site) costs one query instead of one round trip per device —
    at real-fleet scale (hundreds of devices) the per-device loop the
    agent's build_device_status() used isn't viable.
    """

    @pytest.mark.asyncio
    async def test_get_latest_returns_most_recent_value_per_pair(
        self, postgres_url: str, measurements_service: MeasurementsService
    ) -> None:
        # Arrange — two readings for the same (device, measurement); only
        # the later one should come back
        await _seed_measurements_table(postgres_url)
        now = datetime.now(UTC).replace(microsecond=0)
        await _insert_measurement(
            postgres_url,
            ts=now - timedelta(minutes=5),
            site_id="site-G",
            device_id="relay_1",
            measurement="trip_status",
            unit="",
            value=False,
        )
        await _insert_measurement(
            postgres_url,
            ts=now,
            site_id="site-G",
            device_id="relay_1",
            measurement="trip_status",
            unit="",
            value=True,
        )

        # Act
        actual = await measurements_service.get_latest(
            site_id="site-G",
            device_ids=["relay_1"],
            measurements=["trip_status"],
        )

        # Assert
        assert len(actual) == 1
        assert actual[0].device_id == "relay_1"
        assert actual[0].measurement == "trip_status"
        assert actual[0].ts == now
        assert actual[0].value is True

    @pytest.mark.asyncio
    async def test_get_latest_covers_many_devices_and_measurements_in_one_call(
        self, postgres_url: str, measurements_service: MeasurementsService
    ) -> None:
        # Arrange — 3 devices x 2 measurements = 6 series, one reading each
        await _seed_measurements_table(postgres_url)
        now = datetime.now(UTC).replace(microsecond=0)
        for i in range(1, 4):
            for meas, val in (("gpu_1_throttle_reason", "NA"), ("fan_speed", 1800.0)):
                await _insert_measurement(
                    postgres_url,
                    ts=now,
                    site_id="site-H",
                    device_id=f"gpu_node_{i}",
                    measurement=meas,
                    unit="",
                    value=val,
                )

        # Act
        actual = await measurements_service.get_latest(
            site_id="site-H",
            device_ids=["gpu_node_1", "gpu_node_2", "gpu_node_3"],
            measurements=["gpu_1_throttle_reason", "fan_speed"],
        )

        # Assert — all 6 pairs present, one query
        pairs = {(v.device_id, v.measurement): v.value for v in actual}
        assert len(pairs) == 6
        assert pairs[("gpu_node_2", "gpu_1_throttle_reason")] == "NA"
        assert pairs[("gpu_node_3", "fan_speed")] == 1800.0

    @pytest.mark.asyncio
    async def test_get_latest_omits_pairs_with_no_data(
        self, postgres_url: str, measurements_service: MeasurementsService
    ) -> None:
        # Arrange — only one of the two requested pairs has any data
        await _seed_measurements_table(postgres_url)
        await _insert_measurement(
            postgres_url,
            ts=datetime.now(UTC),
            site_id="site-I",
            device_id="cooler_1",
            measurement="fault_word",
            unit="",
            value=0.0,
        )

        # Act — also ask about a device/measurement with zero rows
        actual = await measurements_service.get_latest(
            site_id="site-I",
            device_ids=["cooler_1", "cooler_2"],
            measurements=["fault_word"],
        )

        # Assert — only the pair with real data comes back, no null-filled row
        assert len(actual) == 1
        assert actual[0].device_id == "cooler_1"

    @pytest.mark.asyncio
    async def test_get_latest_scopes_to_requested_site(
        self, postgres_url: str, measurements_service: MeasurementsService
    ) -> None:
        # Arrange — same device/measurement name, different sites
        await _seed_measurements_table(postgres_url)
        await _insert_measurement(
            postgres_url,
            ts=datetime.now(UTC),
            site_id="site-J-other",
            device_id="switch_1",
            measurement="port_link_status",
            unit="",
            value="DOWN",
        )

        # Act — query a different site_id
        actual = await measurements_service.get_latest(
            site_id="site-J",
            device_ids=["switch_1"],
            measurements=["port_link_status"],
        )

        # Assert — the other site's row must not leak through
        assert actual == []
