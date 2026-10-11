"""Unit tests for build_latest_value — pure functions over a fake ServerClient."""

from datetime import UTC, datetime

import pytest

from ..schemas import TableSpec
from ..server_client import (
    LatestValue,
    LatestValuesResponse,
    MeasurementPair,
    SiteDescription,
)
from .latest_value import build_latest_value

_NOW = datetime(2026, 10, 11, 20, 0, tzinfo=UTC)
_TS = datetime(2026, 10, 11, 19, 48, tzinfo=UTC)  # 12 min before _NOW


def _pairs(*specs: tuple[str, str]) -> SiteDescription:
    return SiteDescription(
        site_id="demo-site",
        pairs=[MeasurementPair(device_id=d, measurement=m) for d, m in specs],
    )


def _latest(*specs: tuple[str, str, float | str | bool | None]) -> list[LatestValue]:
    return [
        LatestValue(device_id=d, measurement=m, ts=_TS, value=v) for d, m, v in specs
    ]


class _FakeServerClient:
    """Returns canned ServerClient responses; records calls."""

    def __init__(
        self, description: SiteDescription, latest: list[LatestValue] | None = None
    ) -> None:
        self._description = description
        self._latest = latest or []
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def describe_site(self) -> SiteDescription:
        self.calls.append(("describe_site", {}))
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
        return LatestValuesResponse(site_id="demo-site", values=self._latest)


class TestBuildLatestValue:
    """AAA — one bulk read across every device reporting the measurement."""

    @pytest.mark.asyncio
    async def test_one_row_per_device_and_numeric_summary(self) -> None:
        # Arrange — a second measurement on one device must not leak in
        fake = _FakeServerClient(
            _pairs(
                ("bess_rack_01", "state_of_charge"),
                ("bess_rack_02", "state_of_charge"),
                ("bess_rack_01", "active_power"),
            ),
            _latest(
                ("bess_rack_01", "state_of_charge", 74.2),
                ("bess_rack_02", "state_of_charge", 70.0),
            ),
        )

        # Act
        art, summary = await build_latest_value(
            fake,  # ty: ignore[invalid-argument-type]
            "state_of_charge",
            now=_NOW,
        )

        # Assert
        assert art.kind == "table"
        assert isinstance(art.spec, TableSpec)
        assert [r["device"] for r in art.spec.rows] == ["bess_rack_01", "bess_rack_02"]
        assert fake.calls[1] == (
            "get_latest_measurements",
            {
                "device_ids": ["bess_rack_01", "bess_rack_02"],
                "measurements": ["state_of_charge"],
            },
        )
        assert "2 devices" in summary
        assert "avg 72.1" in summary
        assert "min 70.0 (bess_rack_02)" in summary
        assert "max 74.2 (bess_rack_01)" in summary
        assert "12 min ago" in summary

    @pytest.mark.asyncio
    async def test_spaced_title_case_name_resolves(self) -> None:
        # Arrange — the model passes what the user said, not the exact key
        fake = _FakeServerClient(
            _pairs(("bess_rack_01", "state_of_charge")),
            _latest(("bess_rack_01", "state_of_charge", 74.2)),
        )

        # Act
        art, _ = await build_latest_value(
            fake,  # ty: ignore[invalid-argument-type]
            "State of Charge",
            now=_NOW,
        )

        # Assert
        assert art.kind == "table"
        assert fake.calls[1][1]["measurements"] == ["state_of_charge"]

    @pytest.mark.asyncio
    async def test_unique_substring_resolves(self) -> None:
        # Arrange — "charge" is contained by exactly one measurement
        fake = _FakeServerClient(
            _pairs(
                ("bess_rack_01", "state_of_charge"), ("bess_rack_01", "active_power")
            ),
            _latest(("bess_rack_01", "state_of_charge", 74.2)),
        )

        # Act
        art, _ = await build_latest_value(
            fake,  # ty: ignore[invalid-argument-type]
            "charge",
            now=_NOW,
        )

        # Assert
        assert art.kind == "table"

    @pytest.mark.asyncio
    async def test_ambiguous_name_lists_candidates_without_reading(self) -> None:
        # Arrange — "power" matches two measurements: don't guess
        fake = _FakeServerClient(
            _pairs(("pcs_01", "active_power"), ("pcs_01", "reactive_power"))
        )

        # Act
        art, summary = await build_latest_value(
            fake,  # ty: ignore[invalid-argument-type]
            "power",
            now=_NOW,
        )

        # Assert — error artifact, candidates named, no bulk read issued
        assert art.kind == "error"
        assert "active_power" in summary
        assert "reactive_power" in summary
        assert [c[0] for c in fake.calls] == ["describe_site"]

    @pytest.mark.asyncio
    async def test_unknown_name_lists_everything_available(self) -> None:
        # Arrange
        fake = _FakeServerClient(
            _pairs(("bess_rack_01", "state_of_charge"), ("bess_rack_01", "voltage"))
        )

        # Act
        art, summary = await build_latest_value(
            fake,  # ty: ignore[invalid-argument-type]
            "humidity",
            now=_NOW,
        )

        # Assert
        assert art.kind == "error"
        assert "humidity" in summary
        assert "state_of_charge" in summary
        assert "voltage" in summary

    @pytest.mark.asyncio
    async def test_non_numeric_values_summarised_as_counts(self) -> None:
        # Arrange — a status enum has no average
        fake = _FakeServerClient(
            _pairs(("cdu_01", "status"), ("cdu_02", "status"), ("cdu_03", "status")),
            _latest(
                ("cdu_01", "status", "ok"),
                ("cdu_02", "status", "ok"),
                ("cdu_03", "status", "warn"),
            ),
        )

        # Act
        _, summary = await build_latest_value(
            fake,  # ty: ignore[invalid-argument-type]
            "status",
            now=_NOW,
        )

        # Assert
        assert "2 ok, 1 warn" in summary
        assert "avg" not in summary

    @pytest.mark.asyncio
    async def test_no_recent_readings_is_an_error(self) -> None:
        # Arrange — the pair exists in the inventory but has no data
        fake = _FakeServerClient(_pairs(("bess_rack_01", "state_of_charge")))

        # Act
        art, summary = await build_latest_value(
            fake,  # ty: ignore[invalid-argument-type]
            "state_of_charge",
            now=_NOW,
        )

        # Assert
        assert art.kind == "error"
        assert "No recent readings" in summary
