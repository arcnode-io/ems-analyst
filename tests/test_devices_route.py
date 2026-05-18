"""HTTP route test for GET /sites/{site_id}/devices."""

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.devices.devices_controller import DevicesController
from src.devices.devices_service import DevicesService
from src.devices.dto import DeviceList, DeviceRow


class _FakeDevicesService:
    """Returns a canned DeviceList; records calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def list(self, site_id: str, status: list[str] | None = None) -> DeviceList:
        self.calls.append({"site_id": site_id, "status": status})
        return DeviceList(
            site_id=site_id,
            devices=[
                DeviceRow(device_id="BESS-01", status="ok"),
                DeviceRow(device_id="INV-02", status=None),
            ],
        )


@pytest.fixture
def client() -> tuple[TestClient, _FakeDevicesService]:
    fake = _FakeDevicesService()
    app = FastAPI()
    app.include_router(DevicesController(cast(DevicesService, fake)).router)
    return TestClient(app), fake


class TestDevicesRoute:
    """AAA — controller delegates and shapes JSON."""

    def test_returns_device_list(
        self, client: tuple[TestClient, _FakeDevicesService]
    ) -> None:
        # Arrange
        c, _ = client

        # Act
        response = c.get("/sites/site-D/devices")

        # Assert
        assert response.status_code == 200
        body = response.json()
        assert body["site_id"] == "site-D"
        assert len(body["devices"]) == 2
        assert body["devices"][0]["device_id"] == "BESS-01"
        assert body["devices"][0]["status"] == "ok"
        assert body["devices"][1]["status"] is None

    def test_forwards_status_filter(
        self, client: tuple[TestClient, _FakeDevicesService]
    ) -> None:
        # Arrange
        c, fake = client

        # Act — repeat status query param to send a list
        c.get("/sites/site-D/devices?status=alarm&status=warn")

        # Assert
        assert fake.calls[0]["status"] == ["alarm", "warn"]
