"""HTTP route test for GET /sites/{site_id}/forecast."""

from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.forecasts.dto import ForecastPoint, ForecastSeries
from src.forecasts.forecasts_controller import ForecastsController
from src.forecasts.forecasts_service import ForecastsService

_DEPLOY_HUB: str = "HB_NORTH"


class _FakeForecastsService:
    """Returns a canned ForecastSeries; records calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def get(
        self,
        site_id: str,
        settlement_point: str,
        measurement: str,
        start: datetime,
        end: datetime,
    ) -> ForecastSeries:
        self.calls.append(
            {
                "site_id": site_id,
                "settlement_point": settlement_point,
                "measurement": measurement,
                "start": start,
                "end": end,
            }
        )
        return ForecastSeries(
            site_id=site_id,
            settlement_point=settlement_point,
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
    # Controller carries the deploy's settlement_point (HB_NORTH).
    app.include_router(
        ForecastsController(
            cast(ForecastsService, fake), settlement_point=_DEPLOY_HUB
        ).router
    )
    return TestClient(app), fake


class TestForecastsRoute:
    """AAA — controller maps site → settlement_point + shapes JSON."""

    def test_returns_series_for_site(
        self, client: tuple[TestClient, _FakeForecastsService]
    ) -> None:
        # Arrange
        c, _ = client

        # Act
        response = c.get(
            "/sites/demo-site/forecast",
            params={
                "measurement": "dam_lmp_price",
                "start": "2026-05-17T00:00:00Z",
                "end": "2026-05-18T00:00:00Z",
            },
        )

        # Assert
        assert response.status_code == 200
        body = response.json()
        assert body["site_id"] == "demo-site"
        assert body["settlement_point"] == "HB_NORTH"
        assert body["measurement"] == "dam_lmp_price"
        assert body["model_name"] == "dam-lmp-forecast"
        assert len(body["points"]) == 1
        assert body["points"][0]["value"] == 42.5

    def test_maps_site_to_deploy_settlement_point(
        self, client: tuple[TestClient, _FakeForecastsService]
    ) -> None:
        # Arrange
        c, fake = client

        # Act — caller names a site; controller resolves to the hub
        c.get(
            "/sites/site-X/forecast",
            params={
                "measurement": "dam_lmp_price",
                "start": "2026-05-17T00:00:00Z",
                "end": "2026-05-18T00:00:00Z",
            },
        )

        # Assert — site echoed, query ran against the deploy hub
        call = fake.calls[0]
        assert call["site_id"] == "site-X"
        assert call["settlement_point"] == "HB_NORTH"
