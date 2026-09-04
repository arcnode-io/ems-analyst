"""Unit tests for ScopeFilter — deterministic FakeEmbedder, no network."""

import pytest
from ems_analyst_mcp.clients import Embedder

from .scope_filter import _ANCHORS, _DEFAULT_THRESHOLD, ScopeFilter


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


class TestTunedDefaults:
    """Locks in the live-embedder-probed production config (2026-09-04).

    qwen3-embedding:4b's off-domain noise floor measured 0.25-0.45 against
    the pre-fix anchor set/threshold — "implement fibonacci in python" and
    "capital of France" both passed at 0.30. See scope_filter.py's
    docstring for the probe numbers.
    """

    def test_threshold_above_measured_off_domain_noise_floor(self) -> None:
        assert _DEFAULT_THRESHOLD >= 0.45

    def test_anchors_cover_device_status_and_alarm_queries(self) -> None:
        # "list devices in alarm" scored 0.37 against the original 20
        # anchors — same band as off-domain noise, needed its own anchor.
        assert any("alarm" in a.lower() for a in _ANCHORS)
