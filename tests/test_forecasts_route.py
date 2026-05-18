"""HTTP route test for GET /sites/{site_id}/forecast."""

from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.forecasts.dto import ForecastPoint, ForecastSeries
from src.forecasts.forecasts_controller import ForecastsController
from src.forecasts.forecasts_service import ForecastsService


class _FakeForecastsService:
    """Returns a canned ForecastSeries; records calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def get(
        self,
        site_id: str,
        measurement: str,
        start: datetime,
        end: datetime,
    ) -> ForecastSeries:
        self.calls.append(
            {
                "site_id": site_id,
                "measurement": measurement,
                "start": start,
                "end": end,
            }
        )
        return ForecastSeries(
            site_id=site_id,
            measurement=measurement,
            unit="usd_per_mwh",
            model_name="dam-lmp-forecast",
            model_version=3,
            points=[
                ForecastPoint(
                    forecast_for=datetime(2026, 5, 18, tzinfo=UTC), value=42.5
                ),
            ],
        )


@pytest.fixture
def client() -> tuple[TestClient, _FakeForecastsService]:
    fake = _FakeForecastsService()
    app = FastAPI()
    app.include_router(ForecastsController(cast(ForecastsService, fake)).router)
    return TestClient(app), fake


class TestForecastsRoute:
    """AAA — controller delegates to service + shapes JSON."""

    def test_returns_series_for_site(
        self, client: tuple[TestClient, _FakeForecastsService]
    ) -> None:
        # Arrange
        c, _ = client

        # Act
        response = c.get(
            "/sites/HB_NORTH/forecast",
            params={
                "measurement": "dam_lmp_price",
                "start": "2026-05-17T00:00:00Z",
                "end": "2026-05-18T00:00:00Z",
            },
        )

        # Assert
        assert response.status_code == 200
        body = response.json()
        assert body["site_id"] == "HB_NORTH"
        assert body["measurement"] == "dam_lmp_price"
        assert body["unit"] == "usd_per_mwh"
        assert body["model_name"] == "dam-lmp-forecast"
        assert body["model_version"] == 3
        assert len(body["points"]) == 1
        assert body["points"][0]["value"] == 42.5

    def test_forwards_query_params_to_service(
        self, client: tuple[TestClient, _FakeForecastsService]
    ) -> None:
        # Arrange
        c, fake = client

        # Act
        c.get(
            "/sites/site-X/forecast",
            params={
                "measurement": "dam_lmp_price",
                "start": "2026-05-17T00:00:00Z",
                "end": "2026-05-18T00:00:00Z",
            },
        )

        # Assert
        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call["site_id"] == "site-X"
        assert call["measurement"] == "dam_lmp_price"
