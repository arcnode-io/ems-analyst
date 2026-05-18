import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from ipaddress import IPv4Address

from ems_analyst_agent.demo_seed import seed_measurements
from fastapi import FastAPI
from pydantic_settings import BaseSettings
from src.app_controller import AppController
from src.call_api.call_api_module import CallApiModule
from src.config import LogLevel, load_config
from src.conversations.conversation_module import ConversationModule
from src.description.description_module import DescriptionModule
from src.devices.devices_module import DevicesModule
from src.forecasts.forecasts_module import ForecastsModule
from src.measurements.measurements_module import MeasurementsModule

log = logging.getLogger(__name__)


class Settings(BaseSettings):  # type: ignore[explicit-any]  # upstream: pydantic-settings PRs #557/#559 reverted Any fix
    """Application settings with all config values and override capability."""

    log_level: LogLevel
    port: int
    host: IPv4Address
    e2e: bool
    reload: bool


class AppModule:
    """Module for creating basic FastAPI applications."""

    def __init__(self) -> None:
        """Initialize the app module with settings."""
        config = load_config()
        self.settings = Settings(
            log_level=config.log_level,
            port=config.port,
            host=config.host,
            e2e=config.e2e,
            reload=config.reload,
        )

    def import_module(self, app: FastAPI) -> None:
        """Register all routes — health, call_api, chat, telemetry surfaces."""
        for mod in (
            AppController(),
            CallApiModule(),
            ConversationModule(),
            MeasurementsModule(),
            DevicesModule(),
            DescriptionModule(),
            ForecastsModule(),
        ):
            app.include_router(mod.router)

    def create_app(self) -> FastAPI:
        """Create and configure the basic FastAPI application."""
        app = FastAPI(lifespan=_lifespan)
        self.import_module(app)
        return app


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Boot/teardown hook — ENV=demo triggers measurements seed.

    Seed is idempotent: skips when rows already present (e.g. restart
    against a persistent volume).
    """
    if os.environ.get("ENV") == "demo":
        timeseries_url = os.environ.get("TIMESERIES_URL")
        if timeseries_url:
            rows = await seed_measurements(timeseries_url)
            log.info("ENV=demo: measurements table now has %d rows", rows)
        else:
            log.warning("ENV=demo but TIMESERIES_URL unset; skipping seed")
    yield
