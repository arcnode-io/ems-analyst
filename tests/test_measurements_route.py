"""HTTP route test for GET /sites/{site_id}/measurements.

Verifies the controller wires device_id/measurement/start/end/aggregation
query params correctly and shapes JSON per the bucketed MeasurementSeries
DTO.
"""

from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.measurements.dto import Aggregation, MeasurementPoint, MeasurementSeries
from src.measurements.measurements_controller import MeasurementsController
from src.measurements.measurements_service import MeasurementsService


class _FakeMeasurementsService:
    """Returns a canned bucketed series; records calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def get(
        self,
        site_id: str,
        device_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
        aggregation: Aggregation = "mean",
    ) -> MeasurementSeries:
        self.calls.append(
            {
                "site_id": site_id,
                "device_id": device_id,
                "measurement": measurement,
                "start": start,
                "end": end,
                "aggregation": aggregation,
            }
        )
        return MeasurementSeries(
            site_id=site_id,
            device_id=device_id,
            measurement=measurement,
            unit="kw",
            points=[
                MeasurementPoint(ts=datetime(2026, 5, 18, tzinfo=UTC), value=42.5),
                MeasurementPoint(ts=datetime(2026, 5, 18, 1, tzinfo=UTC), value=None),
            ],
        )


@pytest.fixture
def client() -> tuple[TestClient, _FakeMeasurementsService]:
    """FastAPI client with a fake service jacked into the controller."""
    fake = _FakeMeasurementsService()
    app = FastAPI()
    app.include_router(MeasurementsController(cast(MeasurementsService, fake)).router)
    return TestClient(app), fake


class TestMeasurementsRoute:
    """AAA — controller delegates to service + shapes JSON correctly."""

    def test_returns_bucketed_series(
        self, client: tuple[TestClient, _FakeMeasurementsService]
    ) -> None:
        # Arrange
        c, _ = client

        # Act
        response = c.get(
            "/sites/site-A/measurements",
            params={
                "device_id": "device-1",
                "measurement": "power_kw",
                "start": "2026-05-17T00:00:00Z",
                "end": "2026-05-18T00:00:00Z",
            },
        )

        # Assert
        assert response.status_code == 200
        body = response.json()
        assert body["site_id"] == "site-A"
        assert body["device_id"] == "device-1"
        assert body["measurement"] == "power_kw"
        assert body["unit"] == "kw"
        assert len(body["points"]) == 2
        assert body["points"][0]["value"] == 42.5
        assert body["points"][1]["value"] is None

    def test_forwards_aggregation_param_default_mean(
        self, client: tuple[TestClient, _FakeMeasurementsService]
    ) -> None:
        # Arrange
        c, fake = client

        # Act — no aggregation param
        c.get(
            "/sites/site-B/measurements",
            params={
                "device_id": "device-2",
                "measurement": "energy_kwh",
                "start": "2026-05-17T00:00:00Z",
                "end": "2026-05-18T00:00:00Z",
            },
        )

        # Assert default
        assert fake.calls[0]["aggregation"] == "mean"

    def test_forwards_explicit_aggregation(
        self, client: tuple[TestClient, _FakeMeasurementsService]
    ) -> None:
        # Arrange
        c, fake = client

        # Act
        c.get(
            "/sites/site-C/measurements",
            params={
                "device_id": "device-3",
                "measurement": "soc",
                "start": "2026-05-17T00:00:00Z",
                "end": "2026-05-18T00:00:00Z",
                "aggregation": "last",
            },
        )

        # Assert
        assert fake.calls[0]["aggregation"] == "last"
