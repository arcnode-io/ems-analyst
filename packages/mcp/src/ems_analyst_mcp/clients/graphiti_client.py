"""Graphiti knowledge graph client for structured fact retrieval."""

import logging
import os
from typing import Any, Optional, cast
from urllib.parse import unquote, urlsplit, urlunsplit

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.driver import record_parsers as _record_parsers
from graphiti_core.driver.neptune.operations import search_ops as _neptune_search_ops
from graphiti_core.driver.neptune_driver import NeptuneDriver
from graphiti_core.driver.search_interface.search_interface import SearchInterface
from graphiti_core.edges import EntityEdge
from graphiti_core.embedder.client import EmbedderClient
from graphiti_core.llm_client import LLMClient

from ..config import (
    BedrockSettings,
    Config,
    Neo4jGraph,
    NeptuneGraph,
    NoneGraph,
    OllamaSettings,
    ProviderSettings,
)
from ..models import EntityMetadata, SearchResult
from .graphiti_bedrock import (
    BedrockCrossEncoderClient,
    BedrockEmbedderClient,
    BedrockLLMClient,
)
from .graphiti_ollama import (
    OllamaEmbedderClient,
    make_ollama_llm,
    make_ollama_reranker,
)

log = logging.getLogger(__name__)


def _patch_graphiti_neptune() -> None:
    """One of two upstream bugs in graphiti-core 0.28.2's Neptune integration.

    entity_edge_from_record rejects episodes=None. Neptune doesn't support
    multi-valued edge properties, so our seed CSV omits the column entirely.
    The new ops module's cypher uses split(e.episodes, ',') which returns
    NULL when the property is absent, and EntityEdge.episodes is typed
    list[str] (not optional). Default to [] when missing.

    The second upstream bug is handled inline in from_env() — see the
    `driver.search_interface = cast(...)` comment there.
    """
    _orig = _record_parsers.entity_edge_from_record

    # Signature matches upstream entity_edge_from_record(record: Any) -> EntityEdge.
    def _safe(record: Any) -> EntityEdge:  # noqa: ANN401  matches upstream contract
        if record.get("episodes") is None:
            record["episodes"] = []
        return _orig(record)

    # Patch via __dict__ — direct attribute assignment trips ty's
    # function-name identity check on entity_edge_from_record's signature.
    # We're deliberately swapping in a same-signature wrapper.
    _record_parsers.__dict__["entity_edge_from_record"] = _safe
    _neptune_search_ops.__dict__["entity_edge_from_record"] = _safe


_patch_graphiti_neptune()


class GraphitiClient:
    """Client for Graphiti knowledge graph operations."""

    def __init__(self, graphiti: Graphiti) -> None:
        """Wrap an already-constructed Graphiti instance.

        Prefer GraphitiClient.from_env() — direct construction is for tests.
        """
        self.graphiti = graphiti

    @classmethod
    def from_config(cls, config: Config) -> "GraphitiClient":
        """Pick a backend from cfg.graph + the single secret (GRAPH_URL).

        cfg.graph.backend=neo4j → reads GRAPH_URL env (carries creds).
        cfg.graph.backend=neptune → uses cfg.graph.neptune_host + aoss_host.
        cfg.graph.backend=none → RuntimeError; no defaults.
        """
        graph = config.graph

        if isinstance(graph, Neo4jGraph):
            graph_url = os.environ.get("GRAPH_URL")
            if not graph_url:
                raise RuntimeError("graph.backend=neo4j but GRAPH_URL env not set")
            # Reason: neo4j-python rejects URL-embedded creds (ConfigurationError),
            # so we strip user:pass out of GRAPH_URL and hand them to Graphiti
            # via the dedicated kwargs.
            uri, user, password = _split_neo4j_url(graph_url)
            embedder, llm_client, cross_encoder = _build_graphiti_clients(
                config.settings
            )
            return cls(
                Graphiti(
                    uri=uri,
                    user=user,
                    password=password,
                    embedder=embedder,
                    llm_client=llm_client,
                    cross_encoder=cross_encoder,
                )
            )

        if isinstance(graph, NeptuneGraph):
            # Strip `https://` — graphiti's opensearch client prepends scheme
            # itself; double-prefix produces an IPv6-literal-style URL.
            clean_aoss = graph.aoss_host.removeprefix("https://").removeprefix(
                "http://"
            )
            driver = NeptuneDriver(
                host=f"neptune-db://{graph.neptune_host}",
                aoss_host=clean_aoss,
            )
            # Bug 2 — NeptuneDriver builds a NeptuneSearchOperations and assigns
            # it to _search_ops, but graphiti's dispatcher in
            # graphiti_core/search/search_utils.py only checks driver.search_interface
            # (None by default). Falling through routes every search through
            # the legacy Neptune branch (lines 225-268) which appends a second
            # WHERE clause to a cypher that already has one -> MalformedQueryException.
            # Wiring the new ops module to search_interface routes the dispatcher
            # to NeptuneSearchOperations.edge_fulltext_search which constructs
            # the cypher correctly.
            # NeptuneSearchOperations is duck-compatible with SearchInterface
            # (same async method names + signatures used by the dispatcher) but
            # extends SearchOperations, not SearchInterface, so the type checker
            # needs an explicit cast.
            driver.search_interface = cast(SearchInterface, driver.search_ops)
            llm = BedrockLLMClient()
            return cls(
                Graphiti(
                    graph_driver=driver,
                    embedder=BedrockEmbedderClient(),
                    llm_client=llm,
                    cross_encoder=BedrockCrossEncoderClient(llm=llm),
                )
            )

        if isinstance(graph, NoneGraph):
            raise RuntimeError(  # noqa: TRY004 — backend=none is misconfig, not wrong type
                "no graph backend configured — set cfg.graph.backend to "
                "neo4j (with GRAPH_URL env) or neptune (with hosts in cfg)"
            )
        raise TypeError(f"unknown GraphConfig type: {type(graph).__name__}")

    async def search(
        self, query: str, center_node_uuid: Optional[str] = None, limit: int = 10
    ) -> list[SearchResult]:
        """Hybrid search combining semantic, BM25, and graph traversal.

        Raises the underlying Graphiti error on failure — no silent empty list.
        """
        try:
            raw_results = await self.graphiti.search(
                query=query,
                center_node_uuid=center_node_uuid,
            )
        except Exception:
            log.exception("graphiti search failed (query=%r)", query)
            raise
        limited = raw_results[:limit] if raw_results else []
        return [
            SearchResult(
                id=str(getattr(r, "uuid", getattr(r, "id", ""))),
                content=str(getattr(r, "fact", getattr(r, "content", ""))),
                score=getattr(r, "score", None),
                metadata=EntityMetadata(),
            )
            for r in limited
        ]

    async def close(self) -> None:
        """Close the Graphiti client connection."""
        if hasattr(self.graphiti, "close") and callable(self.graphiti.close):
            await self.graphiti.close()  # type: ignore[no-untyped-call]


def _build_graphiti_clients(
    settings: ProviderSettings,
) -> tuple[EmbedderClient, LLMClient, CrossEncoderClient]:
    """Return (embedder, llm_client, cross_encoder) for the active provider.

    Reason: graphiti defaults to OpenAI when these kwargs are absent, which
    breaks airgapped + portal-self-serve deployments per ADR-024. Dispatch
    on the ProviderSettings discriminator so local/airgapped → Ollama and
    cloud commercial/beta → Bedrock.
    """
    if isinstance(settings, BedrockSettings):
        llm = BedrockLLMClient()
        return (
            BedrockEmbedderClient(),
            llm,
            BedrockCrossEncoderClient(llm=llm),
        )
    if isinstance(settings, OllamaSettings):
        return (
            OllamaEmbedderClient(
                base_url=settings.ollama_base_url,
                model=settings.ollama_embedding_model,
            ),
            make_ollama_llm(settings.ollama_base_url, settings.ollama_chat_model),
            make_ollama_reranker(settings.ollama_base_url, settings.ollama_chat_model),
        )
    raise TypeError(f"unknown ProviderSettings type: {type(settings).__name__}")


def _split_neo4j_url(url: str) -> tuple[str, Optional[str], Optional[str]]:
    """Extract (clean_uri, user, password) from a Neo4j URL.

    Aura-style packaging puts creds in the URL for env-var convenience;
    neo4j-python won't accept them there, so we strip them out.

    Reason: parts.username/password return the *raw* substring — urlsplit
    does NOT decode percent-encoding. Callers may URL-encode creds to
    survive special chars (@, !, etc. — common in shared dev passwords)
    so we unquote here before handing the cred to the Neo4j driver. Raw
    (unencoded) creds also work since unquote is a no-op on plain text.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    clean = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    user = unquote(parts.username) if parts.username else None
    password = unquote(parts.password) if parts.password else None
    return clean, user, password
