"""HTTP route test for GET /description.

Single-site deploy: no site_id in the path; controller holds it.
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
    """Returns a canned SiteDescription; records calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def describe(self, site_id: str) -> SiteDescription:
        self.calls.append(site_id)
        return SiteDescription(
            site_id=site_id,
            pairs=[
                MeasurementPair(device_id="BESS-01", measurement="soc", samples=24),
                MeasurementPair(
                    device_id="INV-02", measurement="power_kw", samples=144
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
    """AAA — controller delegates and shapes JSON."""

    def test_returns_inventory(
        self, client: tuple[TestClient, _FakeDescriptionService]
    ) -> None:
        # Arrange
        c, fake = client

        # Act
        response = c.get("/description")

        # Assert
        assert response.status_code == 200
        body = response.json()
        assert body["site_id"] == _DEPLOY_SITE
        assert fake.calls[0] == _DEPLOY_SITE
        assert len(body["pairs"]) == 2
        assert body["pairs"][0]["device_id"] == "BESS-01"
        assert body["pairs"][0]["measurement"] == "soc"
        assert body["pairs"][0]["samples"] == 24
