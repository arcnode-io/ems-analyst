"""Unit tests for ServerClient — pook-mocked HTTP against ems-analyst-server.

ServerClient is the agent's REST surface to server. Replaces direct
TimeseriesClient SQL — the agent is just another client of server, same
as HMI. Four endpoints: measurements, devices, description, forecast.
"""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pook
import pytest

from src.ems_analyst_agent.server_client import ServerClient

_BASE: str = "http://server.test"


@pytest.fixture(autouse=True)
def _pook_lifecycle() -> Generator[None]:
    pook.on()
    yield
    pook.off()
    pook.reset()


def _ts(s: str) -> str:
    return datetime.fromisoformat(s).isoformat()


class TestServerClientMeasurements:
    """AAA — measurements call hits the right URL and parses the response."""

    @pytest.mark.asyncio
    async def test_get_measurements_parses_bucketed_series(self) -> None:
        # Arrange
        body = {
            "site_id": "site-A",
            "device_id": "BESS-01",
            "measurement": "power_kw",
            "unit": "kw",
            "points": [
                {"ts": "2026-05-18T01:00:00+00:00", "value": 42.5},
                {"ts": "2026-05-18T02:00:00+00:00", "value": None},
            ],
        }
        pook.get(f"{_BASE}/measurements").reply(200).json(body)
        client = ServerClient(base_url=_BASE)

        # Act
        actual = await client.get_measurements(
            device_id="BESS-01",
            measurement="power_kw",
            start=datetime(2026, 5, 18, tzinfo=UTC),
            end=datetime(2026, 5, 18, tzinfo=UTC) + timedelta(hours=3),
        )

        # Assert
        assert actual.site_id == "site-A"
        assert actual.device_id == "BESS-01"
        assert actual.unit == "kw"
        assert len(actual.points) == 2
        assert actual.points[0].value == 42.5
        assert actual.points[1].value is None


class TestServerClientDevices:
    @pytest.mark.asyncio
    async def test_list_devices_parses_list(self) -> None:
        # Arrange
        body = {
            "site_id": "site-D",
            "devices": [
                {"device_id": "BESS-01", "status": "ok"},
                {"device_id": "INV-02", "status": None},
            ],
        }
        pook.get(f"{_BASE}/devices").reply(200).json(body)
        client = ServerClient(base_url=_BASE)

        # Act
        actual = await client.list_devices()

        # Assert
        assert actual.site_id == "site-D"
        assert len(actual.devices) == 2
        assert actual.devices[0].status == "ok"
        assert actual.devices[1].status is None


class TestServerClientDescription:
    @pytest.mark.asyncio
    async def test_describe_site_parses_pairs(self) -> None:
        # Arrange
        body = {
            "site_id": "site-E",
            "pairs": [
                {"device_id": "BESS-01", "measurement": "soc", "samples": 24},
                {"device_id": "INV-02", "measurement": "power_kw", "samples": 144},
            ],
        }
        pook.get(f"{_BASE}/description").reply(200).json(body)
        client = ServerClient(base_url=_BASE)

        # Act
        actual = await client.describe_site()

        # Assert
        assert len(actual.pairs) == 2
        assert actual.pairs[0].device_id == "BESS-01"
        assert actual.pairs[0].samples == 24


class TestServerClientForecast:
    @pytest.mark.asyncio
    async def test_get_forecast_parses_series(self) -> None:
        # Arrange
        body = {
            "site_id": "HB_NORTH",
            "measurement": "dam_lmp_price",
            "unit": "usd_per_mwh",
            "model_name": "dam-lmp-forecast",
            "model_version": 3,
            "points": [
                {"forecast_for": "2026-05-18T01:00:00+00:00", "value": 38.2},
                {"forecast_for": "2026-05-18T02:00:00+00:00", "value": 41.7},
            ],
        }
        pook.get(f"{_BASE}/forecast").reply(200).json(body)
        client = ServerClient(base_url=_BASE)

        # Act
        actual = await client.get_forecast(
            measurement="dam_lmp_price",
            start=datetime(2026, 5, 18, tzinfo=UTC),
            end=datetime(2026, 5, 18, tzinfo=UTC) + timedelta(hours=3),
        )

        # Assert
        assert actual.model_name == "dam-lmp-forecast"
        assert actual.model_version == 3
        assert len(actual.points) == 2
        assert actual.points[0].value == 38.2
