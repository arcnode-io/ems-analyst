"""Per-stage + per-customer configuration loader.

Mirrors python-mcp-server's discriminated-union shape so the embedder
provider drives chat + memory together (one llm_provider per customer).

cfg.yml shape: cfg[ENV][customers][CUSTOMER_ENV] -> {Bedrock|Ollama}Settings.
"""

import enum
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_ai.models import Model
from pydantic_ai.models.bedrock import BedrockConverseModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from python_mcp_server.config import (
    BedrockSettings,
    CustomerEnv,
    CustomerSettings,
    OllamaSettings,
)


class LogLevel(enum.StrEnum):
    """Stdlib logging level names; StrEnum so cfg.yml strings parse directly."""

    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"
    DEBUG = "DEBUG"


class StageConfig(BaseModel):
    """One stage block in cfg.yml."""

    log_level: LogLevel
    e2e: bool = False
    customers: dict[CustomerEnv, CustomerSettings]


class _ConfigMap(BaseModel):
    local: StageConfig
    beta: StageConfig


class Config(BaseModel):
    """Resolved runtime config for one process."""

    log_level: LogLevel
    e2e: bool = False
    settings: CustomerSettings


def load_config() -> Config:
    """Resolve cfg[ENV][customers][CUSTOMER_ENV] -> Config.

    ENV defaults to local; CUSTOMER_ENV defaults to defense.
    """
    cfg_path = Path(__file__).parent.parent.parent / "cfg.yml"
    with open(cfg_path) as file:
        config_map = _ConfigMap(**yaml.safe_load(file))
    env = os.environ.get("ENV", "local")
    customer_env_raw = os.environ.get("CUSTOMER_ENV", "defense")
    if customer_env_raw not in ("commercial", "defense", "airgapped"):
        raise ValueError(
            f"CUSTOMER_ENV must be commercial|defense|airgapped, got {customer_env_raw!r}"
        )
    customer_env: CustomerEnv = customer_env_raw  # ty: ignore[invalid-assignment]
    stage = config_map.local if env != "beta" else config_map.beta
    return Config(
        log_level=stage.log_level,
        e2e=stage.e2e,
        settings=stage.customers[customer_env],
    )


def chat_model(settings: CustomerSettings) -> Model:
    """pydantic-ai Model for the customer's chat provider.

    Bedrock customers -> BedrockConverseModel (us.* CRIS prefix mandatory
    per ADR-024). Ollama customers -> OllamaModel against the configured
    base URL (works for arcnode dev endpoint + customer-hosted appliance).
    """
    if isinstance(settings, BedrockSettings):
        return BedrockConverseModel(settings.bedrock_chat_model_id)
    if isinstance(settings, OllamaSettings):
        # Ollama exposes an OpenAI-compatible /v1/chat/completions endpoint
        # so we drive it with OpenAIChatModel + a custom base_url. Same
        # path airgapped customers use against their own Ollama appliance.
        return OpenAIChatModel(
            settings.ollama_chat_model,
            provider=OpenAIProvider(
                base_url=settings.ollama_base_url, api_key="ollama"
            ),
        )
    raise TypeError(f"unknown settings type: {type(settings).__name__}")


class _ZuluFormatter(logging.Formatter):
    """Color level names + Zulu timestamp formatter."""

    def format(self, record: logging.LogRecord) -> str:
        """Format with Zulu time + level + message."""
        zulu_time = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return f"{zulu_time}  {record.levelname}: {record.getMessage()}"


def setup_logger(config: Config) -> None:
    """Color level names + Zulu timestamp formatter."""
    for ind, lvl in enumerate(
        [logging.ERROR, logging.INFO, logging.WARNING, logging.DEBUG],
    ):
        logging.addLevelName(
            lvl,
            f"\033[0;3{ind + 1}m%s\033[1;0m" % logging.getLevelName(lvl),
        )
    logging.basicConfig(
        level=config.log_level.value, handlers=[logging.StreamHandler()]
    )
    for handler in logging.root.handlers:
        handler.setFormatter(_ZuluFormatter())
