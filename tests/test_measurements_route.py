"""HTTP route test for GET /sites/{site_id}/measurements.

Uses FastAPI TestClient + a fake service injected through the module
factory — proves the controller wires query params correctly and shapes
the JSON response per the DTO.
"""

from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.measurements.dto import MeasurementPoint, MeasurementSeries
from src.measurements.measurements_controller import MeasurementsController
from src.measurements.measurements_service import MeasurementsService


class _FakeMeasurementsService:
    """Returns a canned MeasurementSeries; records what it was called with."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def get(
        self,
        site_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
    ) -> MeasurementSeries:
        self.calls.append(
            {
                "site_id": site_id,
                "measurement": measurement,
                "start": start,
                "end": end,
            }
        )
        return MeasurementSeries(
            site_id=site_id,
            measurement=measurement,
            unit="kw",
            points=[
                MeasurementPoint(ts=datetime(2026, 5, 18, tzinfo=UTC), value=42.5),
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

    def test_returns_series_for_site(
        self, client: tuple[TestClient, _FakeMeasurementsService]
    ) -> None:
        # Arrange
        c, _ = client

        # Act
        response = c.get(
            "/sites/site-A/measurements",
            params={
                "measurement": "power_kw",
                "start": "2026-05-17T00:00:00Z",
                "end": "2026-05-18T00:00:00Z",
            },
        )

        # Assert
        assert response.status_code == 200
        body = response.json()
        assert body["site_id"] == "site-A"
        assert body["measurement"] == "power_kw"
        assert body["unit"] == "kw"
        assert len(body["points"]) == 1
        assert body["points"][0]["value"] == 42.5

    def test_forwards_query_params_to_service(
        self, client: tuple[TestClient, _FakeMeasurementsService]
    ) -> None:
        # Arrange
        c, fake = client

        # Act
        c.get(
            "/sites/site-B/measurements",
            params={
                "measurement": "energy_kwh",
                "start": "2026-05-17T00:00:00Z",
                "end": "2026-05-18T00:00:00Z",
            },
        )

        # Assert
        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call["site_id"] == "site-B"
        assert call["measurement"] == "energy_kwh"
