import logging
import os
from ipaddress import IPv4Address
from typing import cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings
from src.app_controller import AppController
from src.call_api.call_api_module import CallApiModule
from src.config import LogLevel, load_config
from src.conversations.conversation_module import ConversationModule
from src.demo.demo_data import DemoData
from src.description.description_module import DescriptionModule
from src.description.description_service import DescriptionService
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

        ENV=demo: /measurements + /description are served from a shared
        in-memory CSV mock (`DemoData`) — no Postgres measurements table.
        forecasts + chat still hit real backends.
        """
        if os.environ.get("ENV") == "demo":
            demo = DemoData()
            measurements = MeasurementsModule(cast(MeasurementsService, demo))
            description = DescriptionModule(cast(DescriptionService, demo))
        else:
            measurements = MeasurementsModule()
            description = DescriptionModule()
        for mod in (
            AppController(),
            CallApiModule(),
            ConversationModule(),
            measurements,
            description,
            ForecastsModule(),
        ):
            app.include_router(mod.router)

    def create_app(self) -> FastAPI:
        """Create and configure the basic FastAPI application."""
        app = FastAPI()
        # The HMI is served from a different origin, so a browser fires a
        # CORS preflight before every /analyst/chat POST. Allow all —
        # this API carries no cookies/credentials. Tighten to the HMI
        # origin if that ever changes.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self.import_module(app)
        return app
