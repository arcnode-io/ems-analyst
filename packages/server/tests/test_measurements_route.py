"""HTTP route test for GET /measurements.

Single-site deploy: no site_id in the path; the controller holds the
deploy site_id. Verifies query-param wiring + JSON shape.
"""

from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.measurements.dto import (
    Aggregation,
    LatestValue,
    MeasurementPoint,
    MeasurementSeries,
)
from src.measurements.measurements_controller import MeasurementsController
from src.measurements.measurements_service import MeasurementsService

_DEPLOY_SITE: str = "demo-site"


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
        bucket_s: int = 3600,
    ) -> MeasurementSeries:
        self.calls.append(
            {
                "site_id": site_id,
                "device_id": device_id,
                "measurement": measurement,
                "start": start,
                "end": end,
                "aggregation": aggregation,
                "bucket_s": bucket_s,
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

    async def get_latest(
        self,
        site_id: str,
        device_ids: list[str],
        measurements: list[str],
    ) -> list[LatestValue]:
        self.calls.append(
            {
                "site_id": site_id,
                "device_ids": device_ids,
                "measurements": measurements,
            }
        )
        return [
            LatestValue(
                device_id=device_ids[0],
                measurement=measurements[0],
                ts=datetime(2026, 5, 18, tzinfo=UTC),
                value=True,
            )
        ]


@pytest.fixture
def client() -> tuple[TestClient, _FakeMeasurementsService]:
    """FastAPI client with a fake service jacked into the controller."""
    fake = _FakeMeasurementsService()
    app = FastAPI()
    app.include_router(
        MeasurementsController(
            cast(MeasurementsService, fake), site_id=_DEPLOY_SITE
        ).router
    )
    return TestClient(app), fake


class TestMeasurementsRoute:
    """AAA — controller delegates to service + shapes JSON correctly."""

    def test_returns_bucketed_series(
        self, client: tuple[TestClient, _FakeMeasurementsService]
    ) -> None:
        # Arrange
        c, fake = client

        # Act
        response = c.get(
            "/measurements",
            params={
                "device_id": "device-1",
                "measurement": "power_kw",
                "start": "2026-05-17T00:00:00Z",
                "end": "2026-05-18T00:00:00Z",
            },
        )

        # Assert — deploy site_id used, JSON shaped
        assert response.status_code == 200
        body = response.json()
        assert body["site_id"] == _DEPLOY_SITE
        assert fake.calls[0]["site_id"] == _DEPLOY_SITE
        assert body["device_id"] == "device-1"
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
            "/measurements",
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
            "/measurements",
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

    def test_analyst_prefixed_path_works(
        self, client: tuple[TestClient, _FakeMeasurementsService]
    ) -> None:
        """The HMI's nginx only proxies /analyst/*, so this path must exist."""
        # Arrange
        c, fake = client

        # Act
        response = c.get(
            "/analyst/measurements",
            params={
                "device_id": "meter_01",
                "measurement": "active_power",
                "start": "2026-05-17T00:00:00Z",
                "end": "2026-05-18T00:00:00Z",
            },
        )

        # Assert — same behavior as the bare /measurements alias
        assert response.status_code == 200
        assert fake.calls[0]["device_id"] == "meter_01"

    def test_bucket_s_defaults_to_3600(
        self, client: tuple[TestClient, _FakeMeasurementsService]
    ) -> None:
        # Arrange
        c, fake = client

        # Act — no bucket_s param
        c.get(
            "/analyst/measurements",
            params={
                "device_id": "device-4",
                "measurement": "power_kw",
                "start": "2026-05-17T00:00:00Z",
                "end": "2026-05-18T00:00:00Z",
            },
        )

        # Assert — unchanged default behavior
        assert fake.calls[0]["bucket_s"] == 3600

    def test_bucket_s_forwards_explicit_value(
        self, client: tuple[TestClient, _FakeMeasurementsService]
    ) -> None:
        # Arrange
        c, fake = client

        # Act — 10-second buckets, as the HMI's power-balance chart needs
        c.get(
            "/analyst/measurements",
            params={
                "device_id": "device-5",
                "measurement": "active_power",
                "start": "2026-05-17T00:00:00Z",
                "end": "2026-05-18T00:00:00Z",
                "bucket_s": 10,
            },
        )

        # Assert
        assert fake.calls[0]["bucket_s"] == 10


class TestMeasurementsLatestRoute:
    """AAA — GET /analyst/measurements/latest, the bulk lookup for rollups."""

    def test_returns_latest_values(
        self, client: tuple[TestClient, _FakeMeasurementsService]
    ) -> None:
        # Arrange
        c, fake = client

        # Act — repeated query params for both list fields
        response = c.get(
            "/analyst/measurements/latest",
            params=[
                ("device_ids", "relay_1"),
                ("device_ids", "relay_2"),
                ("measurements", "trip_status"),
            ],
        )

        # Assert
        assert response.status_code == 200
        body = response.json()
        assert body["site_id"] == _DEPLOY_SITE
        assert body["values"][0]["device_id"] == "relay_1"
        assert body["values"][0]["value"] is True
        assert fake.calls[0]["device_ids"] == ["relay_1", "relay_2"]
        assert fake.calls[0]["measurements"] == ["trip_status"]

    def test_unprefixed_alias_works(
        self, client: tuple[TestClient, _FakeMeasurementsService]
    ) -> None:
        # Arrange
        c, fake = client

        # Act
        response = c.get(
            "/measurements/latest",
            params=[("device_ids", "cooler_1"), ("measurements", "fault_word")],
        )

        # Assert
        assert response.status_code == 200
        assert fake.calls[0]["device_ids"] == ["cooler_1"]
