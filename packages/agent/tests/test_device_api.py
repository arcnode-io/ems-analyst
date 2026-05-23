"""Tests for DeviceApiClient — pook-mocked HTTP + bundled demo mock."""

import os
from collections.abc import Generator

import pook
import pytest

from src.ems_analyst_agent.device_api import DeviceApiClient, DtmView

_BASE: str = "http://device-api.test"

_FAKE_DTM: dict[str, object] = {
    "deployment_uuid": "00000000-0000-0000-0000-000000000001",
    "devices": {
        "bess_module_01": {
            "device_id": "bess_module_01",
            "template": "bess_module",
            "parent": None,
            "display_name": "BESS-01",
        },
        "compute_module_01": {
            "device_id": "compute_module_01",
            "template": "compute_module",
            "parent": None,
            "display_name": "ARC-COMPUTE-01",
        },
        "revenue_meter_01": {
            "device_id": "revenue_meter_01",
            "template": "revenue_meter",
            "parent": "grid_module_01",
            "display_name": "GRD-RM-001",
        },
    },
}


@pytest.fixture(autouse=True)
def _pook_lifecycle() -> Generator[None]:
    pook.on()
    yield
    pook.off()
    pook.reset()


class TestDeviceApiHttp:
    @pytest.mark.asyncio
    async def test_get_topology_parses_dtm(self) -> None:
        # Arrange — non-demo: hits HTTP
        os.environ.pop("ENV", None)
        pook.get(f"{_BASE}/topology/view").reply(200).json(_FAKE_DTM)
        client = DeviceApiClient(base_url=_BASE)

        # Act
        dtm = await client.get_topology()

        # Assert
        assert isinstance(dtm, DtmView)
        assert set(dtm.devices) == {
            "bess_module_01",
            "compute_module_01",
            "revenue_meter_01",
        }


class TestDtmCategory:
    def test_category_of_bess(self) -> None:
        dtm = DtmView.model_validate(_FAKE_DTM)
        assert dtm.category_of("bess_module_01") == "bess"

    def test_category_of_revenue_meter(self) -> None:
        dtm = DtmView.model_validate(_FAKE_DTM)
        assert dtm.category_of("revenue_meter_01") == "grid_intertie"

    def test_category_of_unknown_device_none(self) -> None:
        dtm = DtmView.model_validate(_FAKE_DTM)
        assert dtm.category_of("ghost_99") is None

    def test_devices_in_category_filters_sorted(self) -> None:
        dtm = DtmView.model_validate(_FAKE_DTM)
        assert dtm.devices_in_category("bess") == ["bess_module_01"]
        assert dtm.devices_in_category("compute_load") == ["compute_module_01"]


class TestDeviceApiDemoMock:
    @pytest.mark.asyncio
    async def test_demo_reads_bundled_topology(self) -> None:
        # Arrange — ENV=demo: no HTTP, bundled JSON
        os.environ["ENV"] = "demo"
        try:
            client = DeviceApiClient()
            # Act
            dtm = await client.get_topology()
        finally:
            os.environ.pop("ENV", None)

        # Assert — bundled view.json has the HMI demo device set
        assert "bess_module_01" in dtm.devices
        assert dtm.category_of("bess_module_01") == "bess"
