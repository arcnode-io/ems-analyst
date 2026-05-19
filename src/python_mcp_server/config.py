"""Per-stage configuration loader.

ENV picks the stage block in cfg.defaults.yml. CFG_CUSTOMER_PATH (if set
and the file exists) is deep-merged over the matching stage block before
pydantic parsing — same pattern as ems-industrial-gateway.

Cardinal rule: secrets stay in env. Customer-unique non-secrets live in
cfg.customer.yml. So GRAPH_URL and VECTOR_URL stay env (they embed
user:pass), but graph backend hostnames + IAM ARN ride cfg.
"""

import enum
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, Field


class LogLevel(enum.StrEnum):
    """Stdlib logging level names; StrEnum so cfg strings parse directly."""

    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"
    DEBUG = "DEBUG"


class BedrockSettings(BaseModel):
    """Bedrock provider — cloud stages."""

    llm_provider: Literal["bedrock"]
    bedrock_chat_model_id: str
    bedrock_embedding_model_id: str
    vector_seed_url: str | None = None
    graph_neo4j_seed_url: str | None = None


class OllamaSettings(BaseModel):
    """Ollama provider — airgapped + local dev dogfood.

    Embedding model is Qwen3 (2560d) truncated to 1024 (Matryoshka) so
    schema matches Bedrock Titan dumps.
    """

    llm_provider: Literal["ollama"]
    ollama_base_url: str
    ollama_chat_model: str
    ollama_embedding_model: str
    vector_seed_url: str | None = None
    graph_neo4j_seed_url: str | None = None


ProviderSettings = Annotated[
    BedrockSettings | OllamaSettings, Field(discriminator="llm_provider")
]


class NoneGraph(BaseModel):
    """No graph backend — local dev / unit suites."""

    backend: Literal["none"]


class Neo4jGraph(BaseModel):
    """Neo4j (Aura or self-hosted). GRAPH_URL env carries creds + host."""

    backend: Literal["neo4j"]


class NeptuneGraph(BaseModel):
    """Amazon Neptune + AOSS — defense. CFN UserData writes the hosts +
    role into cfg.customer.yml per customer stack."""

    backend: Literal["neptune"]
    neptune_host: str
    aoss_host: str
    loader_role_arn: str


GraphConfig = Annotated[
    NoneGraph | Neo4jGraph | NeptuneGraph, Field(discriminator="backend")
]


class StageConfig(BaseModel):
    """One stage block in cfg.defaults.yml after customer merge."""

    log_level: LogLevel
    e2e: bool = False  # tests-only: false → pook mocks HTTP; true → real services
    settings: ProviderSettings
    graph: GraphConfig


class Config(BaseModel):
    """Resolved runtime config for a single process."""

    log_level: LogLevel
    e2e: bool = False
    settings: ProviderSettings
    graph: GraphConfig


def load_config() -> Config:
    """Production loader — reads ENV + CFG_CUSTOMER_PATH from process env."""
    defaults = Path(__file__).parent / "cfg.defaults.yml"
    return load_config_from(
        defaults,
        os.environ.get("CFG_CUSTOMER_PATH"),
        os.environ.get("ENV", "local"),
    )


def load_config_from(
    defaults_path: Path, customer_path: str | None, env_name: str
) -> Config:
    """Pure fn for tests. Deep-merge customer over defaults[env_name].

    Unknown ENV (e.g. ENV=ci in pipelines) falls back to the `local`
    stage so transient envs don't have to be enumerated in cfg.
    """
    with open(defaults_path) as f:
        all_data: dict[str, Any] = yaml.safe_load(f)
    stage_data = all_data.get(env_name) or all_data.get("local")
    if stage_data is None:
        raise RuntimeError("cfg.defaults.yml missing both block: local")
    if customer_path:
        cp = Path(customer_path)
        if cp.exists():
            with open(cp) as f:
                customer_data: dict[str, Any] | None = yaml.safe_load(f)
            if customer_data:
                _deep_merge(stage_data, customer_data)
    stage = StageConfig(**stage_data)
    return Config(
        log_level=stage.log_level,
        e2e=stage.e2e,
        settings=stage.settings,
        graph=stage.graph,
    )


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> None:
    """In-place deep-merge of `over` onto `base` — nested dicts recurse,
    scalars + lists overwrite."""
    for key, val in over.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val


class _ZuluFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return (
            f"{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%S.%fZ')}  "
            f"{record.levelname}: {record.getMessage()}"
        )


def setup_logger(config: Config) -> None:
    """Color level names + Zulu timestamp formatter."""
    for ind, lvl in enumerate(
        [logging.ERROR, logging.INFO, logging.WARNING, logging.DEBUG]
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
