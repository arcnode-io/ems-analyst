from fastapi import FastAPI
from src.app_controller import AppController
from src.call_api.call_api_module import CallApiModule
from src.config import load_config, LogLevel
from pydantic_settings import BaseSettings
from ipaddress import IPv4Address


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
        """Register basic routes (app_controller, call_api)."""
        app_controller = AppController()
        call_api = CallApiModule()
        app.include_router(app_controller.router)
        app.include_router(call_api.router)

    def create_app(self) -> FastAPI:
        """Create and configure the basic FastAPI application."""
        app = FastAPI()
        self.import_module(app)
        return app
