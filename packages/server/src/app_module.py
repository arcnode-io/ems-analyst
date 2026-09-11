import logging
import os
from ipaddress import IPv4Address
from typing import cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
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
from src.rate_limit import limiter

# Real callers: local Vite dev (port bumps on conflict, 5173 is the
# default) and the public CloudFront demo site — both alias and raw
# distribution domain, since they serve identical public content and
# excluding the raw one would just silently break it for no security
# gain. Verified with frontend-eng 2026-09-10, not guessed from cfg.yml
# (which has two dead placeholder deploymentHost values — see PR notes).
_ALLOWED_ORIGINS: list[str] = [
    "https://ems.arcnode.io",
    "https://d2vnfwmgofot46.cloudfront.net",
]
_ALLOWED_ORIGIN_REGEX: str = r"http://localhost:517[3-9]"

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
        app.state.limiter = limiter
        # Reason: slowapi's handler is typed narrowly to RateLimitExceeded;
        # Starlette wants the wider Exception signature. Correct at runtime
        # — Starlette only ever calls this registered against that class.
        app.add_exception_handler(
            RateLimitExceeded,
            _rate_limit_exceeded_handler,  # ty: ignore[invalid-argument-type]
        )
        # No SlowAPI*Middleware: it walks app.routes to resolve each
        # handler's __name__ for the exempt check, but classy_fastapi's
        # Routable binds routes as functools.partial(method, self) —
        # partials have no __name__, so the middleware 500s on every
        # request. Not needed anyway: Limiter defaults auto_check=True,
        # so @limiter.limit(...) below does its own check inline using
        # the plain function it closed over at decoration time (before
        # classy_fastapi wraps it) — no middleware in the loop at all.
        # The HMI is served from a different origin, so a browser fires a
        # CORS preflight before every /analyst/chat POST. This API
        # carries no cookies/credentials, so CORS isn't an auth boundary
        # — it's scoped to known callers to reduce browser-based
        # cross-origin abuse as analyst.arcnode.io gets more discoverable.
        # CORS is browser-only: it does nothing against direct curl/httpie
        # access — that's what the rate limiter above is for.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_ALLOWED_ORIGINS,
            allow_origin_regex=_ALLOWED_ORIGIN_REGEX,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self.import_module(app)
        return app
