"""HTTP route test for GET /description.

Single-site deploy: no site_id in the path; the controller holds the
deploy site_id and the response echoes it.
"""

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.description.description_controller import DescriptionController
from src.description.description_service import DescriptionService
from src.description.dto import MeasurementPair, SiteDescription

_DEPLOY_SITE: str = "demo-site"


class _FakeDescriptionService:
    """Returns a canned SiteDescription; records the site it was queried for."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def describe(self, site_id: str) -> SiteDescription:
        self.calls.append(site_id)
        return SiteDescription(
            site_id=site_id,
            pairs=[
                MeasurementPair(
                    device_id="market_01",
                    measurement="dam_clearing_price_usd_per_mwh",
                    samples=712,
                ),
            ],
        )


@pytest.fixture
def client() -> tuple[TestClient, _FakeDescriptionService]:
    fake = _FakeDescriptionService()
    app = FastAPI()
    app.include_router(
        DescriptionController(
            cast(DescriptionService, fake), site_id=_DEPLOY_SITE
        ).router
    )
    return TestClient(app), fake


class TestDescriptionRoute:
    """AAA — controller shapes the inventory JSON, keyed on the deploy site."""

    def test_returns_pairs(
        self, client: tuple[TestClient, _FakeDescriptionService]
    ) -> None:
        # Arrange
        c, _ = client

        # Act
        response = c.get("/description")

        # Assert
        assert response.status_code == 200
        body = response.json()
        assert body["site_id"] == _DEPLOY_SITE
        assert body["pairs"][0]["device_id"] == "market_01"
        assert body["pairs"][0]["measurement"] == "dam_clearing_price_usd_per_mwh"
        assert body["pairs"][0]["samples"] == 712

    def test_query_runs_against_deploy_site(
        self, client: tuple[TestClient, _FakeDescriptionService]
    ) -> None:
        # Arrange
        c, fake = client

        # Act
        c.get("/description")

        # Assert — query keyed on the deploy site, not a path param
        assert fake.calls == [_DEPLOY_SITE]
