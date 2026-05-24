"""Unit tests for ScopeFilter — deterministic FakeEmbedder, no network."""

import pytest
from ems_analyst_mcp.clients import Embedder

from .scope_filter import ScopeFilter


class _FakeEmbedder(Embedder):
    """Returns the vector mapped to each input text — deterministic."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    async def embed(self, text: str) -> list[float]:
        return self._vectors[text]


@pytest.mark.asyncio
class TestInScope:
    """AAA — in_scope returns True/False based on max-cosine threshold."""

    async def test_query_matching_an_anchor_is_in_scope(self) -> None:
        # Arrange — query vector identical to one anchor (cosine = 1.0)
        embedder = _FakeEmbedder({"in domain query": [1.0, 0.0, 0.0]})
        f = ScopeFilter(embedder, threshold=0.5)
        f._anchors = [[1.0, 0.0, 0.0]]  # bypass real anchor seeding

        # Act
        result = await f.in_scope("in domain query")

        # Assert
        assert result is True

    async def test_query_orthogonal_to_all_anchors_is_out_of_scope(self) -> None:
        # Arrange — query is perpendicular to the only anchor (cosine = 0)
        embedder = _FakeEmbedder({"off-domain": [0.0, 1.0, 0.0]})
        f = ScopeFilter(embedder, threshold=0.3)
        f._anchors = [[1.0, 0.0, 0.0]]

        # Act
        result = await f.in_scope("off-domain")

        # Assert
        assert result is False

    async def test_threshold_tunable(self) -> None:
        # Arrange — query has cos = 1/sqrt(2) ≈ 0.707 against the anchor
        embedder = _FakeEmbedder({"q": [1.0, 1.0, 0.0]})

        permissive = ScopeFilter(embedder, threshold=0.5)
        permissive._anchors = [[1.0, 0.0, 0.0]]

        strict = ScopeFilter(embedder, threshold=0.8)
        strict._anchors = [[1.0, 0.0, 0.0]]

        # Act + Assert
        assert await permissive.in_scope("q") is True
        assert await strict.in_scope("q") is False
