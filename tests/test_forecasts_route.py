"""HTTP route test for GET /forecast.

Single-site deploy: no site_id in the path; controller holds the
deploy site_id + settlement_point.
"""

from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.forecasts.dto import ForecastPoint, ForecastSeries
from src.forecasts.forecasts_controller import ForecastsController
from src.forecasts.forecasts_service import ForecastsService

_DEPLOY_SITE: str = "demo-site"
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
    # Controller carries the deploy's site_id + settlement_point.
    app.include_router(
        ForecastsController(
            cast(ForecastsService, fake),
            site_id=_DEPLOY_SITE,
            settlement_point=_DEPLOY_HUB,
        ).router
    )
    return TestClient(app), fake


class TestForecastsRoute:
    """AAA — controller maps deploy site → settlement_point + shapes JSON."""

    def test_returns_series(
        self, client: tuple[TestClient, _FakeForecastsService]
    ) -> None:
        # Arrange
        c, _ = client

        # Act
        response = c.get(
            "/forecast",
            params={
                "measurement": "dam_lmp_price",
                "start": "2026-05-17T00:00:00Z",
                "end": "2026-05-18T00:00:00Z",
            },
        )

        # Assert
        assert response.status_code == 200
        body = response.json()
        assert body["site_id"] == _DEPLOY_SITE
        assert body["settlement_point"] == _DEPLOY_HUB
        assert body["measurement"] == "dam_lmp_price"
        assert body["model_name"] == "dam-lmp-forecast"
        assert len(body["points"]) == 1
        assert body["points"][0]["value"] == 42.5

    def test_query_runs_against_deploy_hub(
        self, client: tuple[TestClient, _FakeForecastsService]
    ) -> None:
        # Arrange
        c, fake = client

        # Act
        c.get(
            "/forecast",
            params={
                "measurement": "dam_lmp_price",
                "start": "2026-05-17T00:00:00Z",
                "end": "2026-05-18T00:00:00Z",
            },
        )

        # Assert — query keyed on the deploy hub, site echoed
        call = fake.calls[0]
        assert call["site_id"] == _DEPLOY_SITE
        assert call["settlement_point"] == _DEPLOY_HUB
