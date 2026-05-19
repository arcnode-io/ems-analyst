"""Unit tests for cfg.defaults.yml + cfg.customer.yml deep-merge loader."""

from pathlib import Path

import pytest

from .config import NeptuneGraph, NoneGraph, load_config_from

_DEFAULTS = """
local:
  log_level: DEBUG
  e2e: false
  settings:
    llm_provider: ollama
    ollama_base_url: http://127.0.0.1:11434/v1
    ollama_chat_model: qwen3.6:35b
    ollama_embedding_model: qwen3-embedding:4b
  graph:
    backend: none
beta:
  log_level: INFO
  e2e: false
  settings:
    llm_provider: bedrock
    bedrock_chat_model_id: us.anthropic.claude-sonnet-4-6
    bedrock_embedding_model_id: amazon.titan-embed-text-v2:0
  graph:
    backend: neo4j
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


def test_defaults_only_picks_stage(tmp_path: Path) -> None:
    """local stage with no customer override → defaults straight through."""
    # Arrange
    defaults = _write(tmp_path, "cfg.defaults.yml", _DEFAULTS)
    # Act
    cfg = load_config_from(defaults, None, "local")
    # Assert
    assert isinstance(cfg.graph, NoneGraph)


def test_customer_yml_flips_graph_to_neptune(tmp_path: Path) -> None:
    """Customer override on beta swaps the graph block to neptune."""
    # Arrange — defense customer override turns beta into neptune backend
    defaults = _write(tmp_path, "cfg.defaults.yml", _DEFAULTS)
    customer = _write(
        tmp_path,
        "cfg.customer.yml",
        """
graph:
  backend: neptune
  neptune_host: db-xyz.cluster-foo.neptune.amazonaws.com
  aoss_host: collection-id.us-east-1.aoss.amazonaws.com
  loader_role_arn: arn:aws:iam::123:role/NeptuneLoader
""",
    )
    # Act
    cfg = load_config_from(defaults, str(customer), "beta")
    # Assert — customer wins for graph; baked settings survive
    assert isinstance(cfg.graph, NeptuneGraph)
    assert cfg.graph.neptune_host == "db-xyz.cluster-foo.neptune.amazonaws.com"
    assert cfg.graph.aoss_host == "collection-id.us-east-1.aoss.amazonaws.com"
    assert cfg.graph.loader_role_arn == "arn:aws:iam::123:role/NeptuneLoader"
    assert cfg.settings.llm_provider == "bedrock"  # untouched key survives


def test_missing_customer_path_falls_back_to_defaults(tmp_path: Path) -> None:
    """CFG_CUSTOMER_PATH set but file missing → defaults silently survive."""
    # Arrange
    defaults = _write(tmp_path, "cfg.defaults.yml", _DEFAULTS)
    # Act — path passed but file does not exist
    cfg = load_config_from(defaults, "/nonexistent/cfg.customer.yml", "beta")
    # Assert
    assert cfg.graph.backend == "neo4j"


def test_unknown_stage_raises(tmp_path: Path) -> None:
    """Loader fails fast when ENV picks a block that doesn't exist."""
    # Arrange
    defaults = _write(tmp_path, "cfg.defaults.yml", _DEFAULTS)
    # Act + Assert
    with pytest.raises(RuntimeError, match="missing block"):
        load_config_from(defaults, None, "prod")
