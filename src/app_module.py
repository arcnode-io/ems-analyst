import logging
import os
from ipaddress import IPv4Address
from typing import cast

from fastapi import FastAPI
from pydantic_settings import BaseSettings
from src.app_controller import AppController
from src.call_api.call_api_module import CallApiModule
from src.config import LogLevel, load_config
from src.conversations.conversation_module import ConversationModule
from src.demo.demo_data import DemoData
from src.forecasts.forecasts_module import ForecastsModule
from src.measurements.measurements_module import MeasurementsModule
from src.measurements.measurements_service import MeasurementsService

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
        """Register all routes — health, call_api, chat, telemetry surfaces.

        ENV=demo: /measurements is served from a shared in-memory CSV
        mock (`DemoData`) — no Postgres measurements table. forecasts +
        chat still hit real backends.
        """
        if os.environ.get("ENV") == "demo":
            demo = DemoData()
            measurements = MeasurementsModule(cast(MeasurementsService, demo))
        else:
            measurements = MeasurementsModule()
        for mod in (
            AppController(),
            CallApiModule(),
            ConversationModule(),
            measurements,
            ForecastsModule(),
        ):
            app.include_router(mod.router)

    def create_app(self) -> FastAPI:
        """Create and configure the basic FastAPI application."""
        app = FastAPI()
        self.import_module(app)
        return app
