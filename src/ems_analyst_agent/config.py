"""Per-stage configuration loader.

Mirrors python-mcp-server's discriminated-union shape so the embedder
provider drives chat + memory together (one llm_provider per stage).

cfg.yml shape: cfg[ENV].settings -> {Bedrock|Ollama}Settings.
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
    OllamaSettings,
    ProviderSettings,
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
    settings: ProviderSettings


class _ConfigMap(BaseModel):
    local: StageConfig
    demo: StageConfig
    beta: StageConfig


class Config(BaseModel):
    """Resolved runtime config for one process."""

    log_level: LogLevel
    e2e: bool = False
    settings: ProviderSettings


def load_config() -> Config:
    """Resolve cfg[ENV] -> Config. ENV defaults to local."""
    cfg_path = Path(__file__).parent / "cfg.yml"
    with open(cfg_path) as file:
        config_map = _ConfigMap(**yaml.safe_load(file))
    env = os.environ.get("ENV", "local")
    stage = {
        "local": config_map.local,
        "demo": config_map.demo,
        "beta": config_map.beta,
    }.get(env, config_map.local)
    return Config(log_level=stage.log_level, e2e=stage.e2e, settings=stage.settings)


def chat_model(settings: ProviderSettings) -> Model:
    """pydantic-ai Model for the provider's chat backend.

    Bedrock -> BedrockConverseModel (us.* CRIS prefix mandatory per ADR-024).
    Ollama -> OpenAIChatModel against the Ollama OpenAI-compatible endpoint
    (same path airgapped customers use against their own appliance).
    """
    if isinstance(settings, BedrockSettings):
        return BedrockConverseModel(settings.bedrock_chat_model_id)
    if isinstance(settings, OllamaSettings):
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
