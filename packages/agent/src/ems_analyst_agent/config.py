"""Per-stage configuration loader. ENV picks stage, CFG_CUSTOMER_PATH merges over it."""

import enum
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_ai.models import Model
from pydantic_ai.models.bedrock import BedrockConverseModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from ems_analyst_mcp.config import (
    BedrockSettings,
    OllamaSettings,
    ProviderSettings,
)


class LogLevel(enum.StrEnum):
    """Stdlib logging level names; StrEnum so YAML strings parse directly."""

    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"
    DEBUG = "DEBUG"


class ErcotSettlementPoint(enum.StrEnum):
    """ERCOT trading hubs — settlement points the customer can pick."""

    HB_NORTH = "HB_NORTH"
    HB_SOUTH = "HB_SOUTH"
    HB_HOUSTON = "HB_HOUSTON"
    HB_WEST = "HB_WEST"
    HB_BUSAVG = "HB_BUSAVG"
    HB_PAN = "HB_PAN"


class ErcotMarket(BaseModel):
    """ERCOT market + settlement-point config block for the deployment."""

    wholesale_market: Literal["ercot"]
    settlement_point: ErcotSettlementPoint


# Add a new ISO arm + hub enum here when the next market comes online.
MarketConfig = Annotated[ErcotMarket, Field(discriminator="wholesale_market")]


class StageConfig(BaseModel):
    """One stage block in cfg.defaults.yml."""

    log_level: LogLevel
    e2e: bool = False
    site_id: str
    settings: ProviderSettings
    market: MarketConfig


class _ConfigMap(BaseModel):
    local: StageConfig
    demo: StageConfig
    beta: StageConfig


class Config(BaseModel):
    """Resolved runtime config for one process."""

    log_level: LogLevel
    e2e: bool = False
    site_id: str
    settings: ProviderSettings
    market: MarketConfig


def load_config() -> Config:
    """Resolve cfg[ENV] -> Config. ENV picks stage; CFG_CUSTOMER_PATH merges over it."""
    defaults_path = Path(__file__).parent / "cfg.defaults.yml"
    with open(defaults_path) as file:
        raw: dict[str, Any] = yaml.safe_load(file)
    env = os.environ.get("ENV", "local")
    customer_path_env = os.environ.get("CFG_CUSTOMER_PATH")
    if customer_path_env:
        customer_path = Path(customer_path_env)
        if customer_path.exists():
            with open(customer_path) as file:
                customer: dict[str, Any] = yaml.safe_load(file) or {}
            stage_raw = raw.get(env, raw["local"])
            if not isinstance(stage_raw, dict):
                raise TypeError(f"cfg.defaults.yml stage {env!r} is not a mapping")
            raw[env] = _deep_merge(stage_raw, customer)
    config_map = _ConfigMap(**raw)
    stage = {
        "local": config_map.local,
        "demo": config_map.demo,
        "beta": config_map.beta,
    }.get(env, config_map.local)
    return Config(
        log_level=stage.log_level,
        e2e=stage.e2e,
        site_id=stage.site_id,
        settings=stage.settings,
        market=stage.market,
    )


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Overlay wins per key. Nested dicts merge recursively; scalars + lists overwrite."""
    out = dict(base)
    for key, val in overlay.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


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
