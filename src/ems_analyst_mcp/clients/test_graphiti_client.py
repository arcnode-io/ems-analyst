"""Unit tests for GraphitiClient.from_config() factory.

Backend dispatch: config.graph.backend is the discriminator. GRAPH_URL
stays env (carries user:pass for Aura/self-hosted Neo4j).
"""

from unittest.mock import MagicMock, patch

import pytest

from ..config import (
    BedrockSettings,
    Config,
    LogLevel,
    Neo4jGraph,
    NeptuneGraph,
    NoneGraph,
    OllamaSettings,
)
from .graphiti_client import GraphitiClient


def _ollama_config(graph: NoneGraph | Neo4jGraph | NeptuneGraph) -> Config:
    return Config(
        log_level=LogLevel.DEBUG,
        e2e=False,
        settings=OllamaSettings(
            llm_provider="ollama",
            ollama_base_url="http://localhost:11434/v1",
            ollama_chat_model="qwen3.6:35b",
            ollama_embedding_model="qwen3-embedding:4b",
        ),
        graph=graph,
    )


def _bedrock_config(graph: NoneGraph | Neo4jGraph | NeptuneGraph) -> Config:
    return Config(
        log_level=LogLevel.INFO,
        e2e=False,
        settings=BedrockSettings(
            llm_provider="bedrock",
            bedrock_chat_model_id="us.anthropic.claude-sonnet-4-6",
            bedrock_embedding_model_id="amazon.titan-embed-text-v2:0",
        ),
        graph=graph,
    )


class TestFromConfigFactory:
    """Branch selection: neo4j backend + GRAPH_URL env → Neo4j;
    neptune backend → Neptune; none → RuntimeError."""

    def test_neo4j_backend_uses_graph_url_env(self) -> None:
        """graph.backend=neo4j + GRAPH_URL → Graphiti built with split creds."""
        # Arrange
        env = {"GRAPH_URL": "neo4j+s://alice:s3cret@host.example:7687"}
        cfg = _ollama_config(Neo4jGraph(backend="neo4j"))
        with (
            patch.dict("os.environ", env, clear=True),
            patch(
                "ems_analyst_mcp.clients.graphiti_client.Graphiti"
            ) as mock_graphiti_class,
        ):
            # Act
            client = GraphitiClient.from_config(cfg)

            # Assert — uri/user/password pinned; provider clients asserted by type
            mock_graphiti_class.assert_called_once()
            kwargs = mock_graphiti_class.call_args.kwargs
            assert kwargs["uri"] == "neo4j+s://host.example:7687"
            assert kwargs["user"] == "alice"
            assert kwargs["password"] == "s3cret"  # noqa: S105 — test fixture
            assert kwargs["embedder"] is not None
            assert kwargs["llm_client"] is not None
            assert kwargs["cross_encoder"] is not None
            assert client.graphiti is mock_graphiti_class.return_value

    def test_neo4j_backend_url_encoded_creds_unquoted(self) -> None:
        """%-encoded creds in GRAPH_URL get decoded before reaching Neo4j."""
        # Arrange — fake password 't!st@x' encoded as 't%21st%40x'
        env = {"GRAPH_URL": "neo4j://alice:t%21st%40x@host.example:7687"}
        cfg = _ollama_config(Neo4jGraph(backend="neo4j"))
        with (
            patch.dict("os.environ", env, clear=True),
            patch(
                "ems_analyst_mcp.clients.graphiti_client.Graphiti"
            ) as mock_graphiti_class,
        ):
            # Act
            GraphitiClient.from_config(cfg)

            # Assert
            kwargs = mock_graphiti_class.call_args.kwargs
            assert kwargs["uri"] == "neo4j://host.example:7687"
            assert kwargs["user"] == "alice"
            assert kwargs["password"] == "t!st@x"  # noqa: S105 — test fixture

    def test_neo4j_backend_wires_ollama_provider_clients(self) -> None:
        """Neo4j branch passes embedder/llm/cross_encoder so graphiti
        doesn't fall back to OpenAI defaults. Local stage → Ollama."""
        # Arrange
        env = {"GRAPH_URL": "bolt://host.example:7687"}
        cfg = _ollama_config(Neo4jGraph(backend="neo4j"))
        with (
            patch.dict("os.environ", env, clear=True),
            patch(
                "ems_analyst_mcp.clients.graphiti_client.Graphiti"
            ) as mock_graphiti_class,
        ):
            # Act
            GraphitiClient.from_config(cfg)

            # Assert
            from .graphiti_ollama import OllamaEmbedderClient

            kwargs = mock_graphiti_class.call_args.kwargs
            assert isinstance(kwargs["embedder"], OllamaEmbedderClient)
            assert kwargs["llm_client"] is not None
            assert kwargs["cross_encoder"] is not None

    def test_neptune_backend_uses_cfg_hosts(self) -> None:
        """graph.backend=neptune reads neptune_host + aoss_host from cfg,
        not env. Bedrock clients wired so graphiti doesn't reach for OpenAI."""
        # Arrange
        cfg = _bedrock_config(
            NeptuneGraph(
                backend="neptune",
                neptune_host="my-cluster.amazonaws.com",
                aoss_host="my-aoss.amazonaws.com",
                loader_role_arn="arn:aws:iam::123:role/Loader",
            )
        )
        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "ems_analyst_mcp.clients.graphiti_client.Graphiti"
            ) as mock_graphiti_class,
            patch(
                "ems_analyst_mcp.clients.graphiti_client.NeptuneDriver"
            ) as mock_driver_class,
            patch("ems_analyst_mcp.clients.graphiti_bedrock.boto3.client"),
        ):
            mock_driver_class.return_value = MagicMock()

            # Act
            client = GraphitiClient.from_config(cfg)

            # Assert — driver built from cfg, not env
            mock_driver_class.assert_called_once_with(
                host="neptune-db://my-cluster.amazonaws.com",
                aoss_host="my-aoss.amazonaws.com",
            )
            mock_graphiti_class.assert_called_once()
            kwargs = mock_graphiti_class.call_args.kwargs
            assert kwargs["graph_driver"] is mock_driver_class.return_value
            from .graphiti_bedrock import (
                BedrockCrossEncoderClient,
                BedrockEmbedderClient,
                BedrockLLMClient,
            )

            assert isinstance(kwargs["embedder"], BedrockEmbedderClient)
            assert isinstance(kwargs["llm_client"], BedrockLLMClient)
            assert isinstance(kwargs["cross_encoder"], BedrockCrossEncoderClient)
            assert client.graphiti is mock_graphiti_class.return_value

    def test_neptune_backend_strips_aoss_scheme(self) -> None:
        """https:// prefix on aoss_host is stripped — graphiti's opensearch
        client adds the scheme itself; double-prefix breaks the URL."""
        # Arrange
        cfg = _bedrock_config(
            NeptuneGraph(
                backend="neptune",
                neptune_host="my-cluster.amazonaws.com",
                aoss_host="https://my-aoss.amazonaws.com",
                loader_role_arn="arn:aws:iam::123:role/Loader",
            )
        )
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("ems_analyst_mcp.clients.graphiti_client.Graphiti"),
            patch(
                "ems_analyst_mcp.clients.graphiti_client.NeptuneDriver"
            ) as mock_driver_class,
            patch("ems_analyst_mcp.clients.graphiti_bedrock.boto3.client"),
        ):
            # Act
            GraphitiClient.from_config(cfg)

            # Assert — stripped scheme on aoss_host
            mock_driver_class.assert_called_once_with(
                host="neptune-db://my-cluster.amazonaws.com",
                aoss_host="my-aoss.amazonaws.com",
            )

    def test_none_backend_raises(self) -> None:
        """graph.backend=none → fail loudly, no defaults."""
        # Arrange
        cfg = _ollama_config(NoneGraph(backend="none"))
        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(RuntimeError, match="no graph backend configured"),
        ):
            # Act + Assert
            GraphitiClient.from_config(cfg)

    def test_neo4j_backend_without_graph_url_env_raises(self) -> None:
        """neo4j backend + missing GRAPH_URL → explicit error.

        Reason: GRAPH_URL is the only secret in this slice; if it's not
        set we should fail at boot, not hand a half-built client to
        graphiti and let it default to OpenAI.
        """
        # Arrange
        cfg = _ollama_config(Neo4jGraph(backend="neo4j"))
        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(RuntimeError, match="GRAPH_URL"),
        ):
            # Act + Assert
            GraphitiClient.from_config(cfg)
