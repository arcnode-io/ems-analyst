"""Unit tests for build_device_status — pure functions over a fake ServerClient.

Split out of telemetry_test.py alongside device_status.py.
"""

from datetime import UTC, datetime

import pytest

from ..schemas import TableSpec
from ..server_client import (
    LatestValue,
    LatestValuesResponse,
    MeasurementPair,
    SiteDescription,
)
from .device_status import build_device_status

_SITE: str = "demo-site"


class _FakeServerClient:
    """Returns canned ServerClient responses; records calls."""

    def __init__(
        self,
        description: SiteDescription | None = None,
        latest_values: list[LatestValue] | None = None,
    ) -> None:
        self._description = description
        self._latest_values = latest_values or []
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def describe_site(self) -> SiteDescription:
        self.calls.append(("describe_site", {}))
        assert self._description is not None
        return self._description

    async def get_latest_measurements(
        self, device_ids: list[str], measurements: list[str]
    ) -> LatestValuesResponse:
        self.calls.append(
            (
                "get_latest_measurements",
                {"device_ids": device_ids, "measurements": measurements},
            )
        )
        matched = [
            v
            for v in self._latest_values
            if v.device_id in device_ids and v.measurement in measurements
        ]
        return LatestValuesResponse(site_id=_SITE, values=matched)


class TestBuildDeviceStatus:
    """AAA — build_device_status collapses per-device status into one table.

    One tool call instead of one query_timeseries per device — the gap
    that made "list devices in alarm" burn most of the 10-tool-call
    budget iterating devices one at a time.
    """

    @pytest.mark.asyncio
    async def test_renders_one_table_row_per_status_device(self) -> None:
        # Arrange — active_power pair should be excluded; only status pairs count
        desc = SiteDescription(
            site_id="demo-site",
            pairs=[
                MeasurementPair(device_id="bess_module_01", measurement="active_power"),
                MeasurementPair(device_id="bess_module_01", measurement="status"),
                MeasurementPair(device_id="cdu_01", measurement="status"),
            ],
        )
        ts = datetime(2026, 5, 18, 1, tzinfo=UTC)
        fake = _FakeServerClient(
            description=desc,
            latest_values=[
                LatestValue(
                    device_id="bess_module_01", measurement="status", ts=ts, value="ok"
                ),
                LatestValue(
                    device_id="cdu_01", measurement="status", ts=ts, value="alarm"
                ),
            ],
        )

        # Act
        art = await build_device_status(fake)  # ty: ignore[invalid-argument-type]

        # Assert — one row per status device, severity carried per row, one
        # bulk call covers both (no per-device loop)
        assert art.kind == "table"
        assert isinstance(art.spec, TableSpec)
        assert len(art.spec.rows) == 2
        assert art.spec.row_severity == ["ok", "alarm"]
        assert art.spec.note == "1 alarm (cdu_01), 1 ok"
        assert [c for c in fake.calls if c[0] == "get_latest_measurements"] == [
            (
                "get_latest_measurements",
                {
                    "device_ids": ["bess_module_01", "cdu_01"],
                    "measurements": ["status"],
                },
            )
        ]

    @pytest.mark.asyncio
    async def test_status_value_is_case_insensitive(self) -> None:
        # Arrange — real telemetry publishes uppercase "OK" for operating_envelope
        desc = SiteDescription(
            site_id="demo-site",
            pairs=[
                MeasurementPair(device_id="operating_envelope", measurement="status")
            ],
        )
        ts = datetime(2026, 5, 18, tzinfo=UTC)
        fake = _FakeServerClient(
            description=desc,
            latest_values=[
                LatestValue(
                    device_id="operating_envelope",
                    measurement="status",
                    ts=ts,
                    value="OK",
                )
            ],
        )

        # Act
        art = await build_device_status(fake)  # ty: ignore[invalid-argument-type]

        # Assert
        assert isinstance(art.spec, TableSpec)
        assert art.spec.row_severity == ["ok"]

    @pytest.mark.asyncio
    async def test_family_rule_grades_devices_with_no_status_measurement(self) -> None:
        # Arrange — gpu_node devices publish throttle reasons, never `status`
        desc = SiteDescription(
            site_id="demo-site",
            pairs=[
                MeasurementPair(
                    device_id="gpu_node_1",
                    measurement="gpu_1_throttle_reason",
                ),
                MeasurementPair(
                    device_id="gpu_node_2",
                    measurement="gpu_1_throttle_reason",
                ),
            ],
        )
        ts = datetime(2026, 5, 18, tzinfo=UTC)
        fake = _FakeServerClient(
            description=desc,
            latest_values=[
                LatestValue(
                    device_id="gpu_node_1",
                    measurement="gpu_1_throttle_reason",
                    ts=ts,
                    value="NA",
                ),
                LatestValue(
                    device_id="gpu_node_2",
                    measurement="gpu_1_throttle_reason",
                    ts=ts,
                    value="SW_POWER_CAP",
                ),
            ],
        )

        # Act
        art = await build_device_status(fake)  # ty: ignore[invalid-argument-type]

        # Assert
        assert isinstance(art.spec, TableSpec)
        assert len(art.spec.rows) == 2
        assert art.spec.row_severity == ["ok", "warn"]
        assert art.spec.rows[1]["status"] == "SW_POWER_CAP"

    @pytest.mark.asyncio
    async def test_device_with_no_status_and_no_family_rule_is_omitted(self) -> None:
        # Arrange — poi_meter has no `status` and isn't in FAMILY_RULES
        desc = SiteDescription(
            site_id="demo-site",
            pairs=[
                MeasurementPair(device_id="poi_meter_1", measurement="active_power")
            ],
        )
        fake = _FakeServerClient(description=desc)

        # Act
        art = await build_device_status(fake)  # ty: ignore[invalid-argument-type]

        # Assert — nothing to grade, same as the empty-inventory case
        assert art.kind == "error"

    @pytest.mark.asyncio
    async def test_note_caps_named_devices_for_a_large_fleet(self) -> None:
        # Arrange — 7 throttled gpu_nodes; only the first _NOTE_MAX_NAMED (5)
        # should be named before the note collapses to "+N more"
        pairs = [
            MeasurementPair(
                device_id=f"gpu_node_{i}",
                measurement="gpu_1_throttle_reason",
            )
            for i in range(1, 8)
        ]
        desc = SiteDescription(site_id="demo-site", pairs=pairs)
        ts = datetime(2026, 5, 18, tzinfo=UTC)
        fake = _FakeServerClient(
            description=desc,
            latest_values=[
                LatestValue(
                    device_id=f"gpu_node_{i}",
                    measurement="gpu_1_throttle_reason",
                    ts=ts,
                    value="SW_POWER_CAP",
                )
                for i in range(1, 8)
            ],
        )

        # Act
        art = await build_device_status(fake)  # ty: ignore[invalid-argument-type]

        # Assert
        assert isinstance(art.spec, TableSpec)
        assert art.spec.note is not None
        assert "+2 more" in art.spec.note
        assert art.spec.note.count("gpu_node_") == 5

    @pytest.mark.asyncio
    async def test_no_status_devices_returns_error_artifact(self) -> None:
        # Arrange
        desc = SiteDescription(
            site_id="demo-site",
            pairs=[
                MeasurementPair(
                    device_id="market_01",
                    measurement="dam_clearing_price_usd_per_mwh",
                )
            ],
        )
        fake = _FakeServerClient(description=desc)

        # Act
        art = await build_device_status(fake)  # ty: ignore[invalid-argument-type]

        # Assert
        assert art.kind == "error"
