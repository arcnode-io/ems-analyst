"""Unit tests for build_topology — DtmView → TableSpec — and get_topology's
once-per-turn cache guard.
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, Mock

import pytest

from ..device_api import DeviceApiClient, DtmView
from ..schemas import TableSpec
from ._common import _TelemetryDeps
from .topology_tool import build_topology, get_topology

_DTM = {
    "deployment_uuid": "00000000-0000-0000-0000-000000000001",
    "devices": {
        "bess_module_01": {
            "device_id": "bess_module_01",
            "template": "bess_module",
            "parent": None,
            "display_name": "BESS-01",
        },
        "cdu_01": {
            "device_id": "cdu_01",
            "template": "cdu",
            "parent": "compute_module_01",
            "display_name": "CDU-01",
        },
    },
}


def test_build_topology_renders_device_table() -> None:
    # Arrange
    dtm = DtmView.model_validate(_DTM)

    # Act
    art = build_topology(dtm)

    # Assert
    assert art.kind == "table"
    assert isinstance(art.spec, TableSpec)
    assert len(art.spec.rows) == 2
    # sorted by device_id — bess before cdu
    assert art.spec.rows[0]["device"] == "bess_module_01"
    assert art.spec.rows[1]["parent"] == "compute_module_01"


def test_build_topology_empty_dtm_returns_error() -> None:
    # Arrange
    dtm = DtmView.model_validate(
        {"deployment_uuid": "00000000-0000-0000-0000-000000000001", "devices": {}}
    )

    # Act
    art = build_topology(dtm)

    # Assert
    assert art.kind == "error"


@dataclass
class _FakeCtx:
    """Minimal RunContext stand-in — the wrapper only ever reads `.deps`."""

    deps: _TelemetryDeps


class TestGetTopologyCache:
    """AAA — a repeat get_topology call in the same turn skips the refetch."""

    @pytest.mark.asyncio
    async def test_second_call_reuses_cache_without_refetching(self) -> None:
        # Arrange — Mock(spec=...) satisfies the wrapper's isinstance guard
        dtm = DtmView.model_validate(_DTM)
        fake_client = Mock(spec=DeviceApiClient)
        fake_client.get_topology = AsyncMock(return_value=dtm)
        deps = _TelemetryDeps(device_api=fake_client)
        ctx = _FakeCtx(deps=deps)

        # Act
        await get_topology(ctx)  # ty: ignore[invalid-argument-type]
        second_result = await get_topology(ctx)  # ty: ignore[invalid-argument-type]

        # Assert — device-api hit once; second call served from cache
        assert fake_client.get_topology.call_count == 1
        assert "already have" in second_result.lower()
        assert len(deps.artifacts) == 2  # both appended; _presentable dedupes later
