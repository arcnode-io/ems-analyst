"""Unit tests for ScopeFilter — deterministic FakeEmbedder, no network."""

import pytest
from ems_analyst_mcp.clients import Embedder
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart

from .scope_filter import _ANCHORS, _DEFAULT_THRESHOLD, ScopeFilter


class _FakeEmbedder(Embedder):
    """Returns the vector mapped to each input text — deterministic.

    Also records every embedded text, so a test can assert the cheap
    single-message path never pays for a second (context) embed call.
    """

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
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


@pytest.mark.asyncio
class TestInScopeWithContext:
    """AAA — a context-dependent follow-up gets a second, context-aided look.

    Bare-query-passes stays a single embed call (today's fast path,
    unchanged cost). Only a bare-query failure pays for a second embed —
    and only when there's history to draw on.
    """

    async def test_bare_query_pass_never_pays_for_a_second_embed_call(self) -> None:
        # Arrange — query alone already matches the anchor
        embedder = _FakeEmbedder({"in domain query": [1.0, 0.0, 0.0]})
        f = ScopeFilter(embedder, threshold=0.5)
        f._anchors = [[1.0, 0.0, 0.0]]
        history: list[ModelRequest | ModelResponse] = [
            ModelResponse(parts=[TextPart(content="prior reply")])
        ]

        # Act
        result = await f.in_scope("in domain query", message_history=history)

        # Assert — fast path only, no context-retry embed
        assert result is True
        assert embedder.calls == ["in domain query"]

    async def test_context_free_followup_passes_with_last_reply_folded_in(self) -> None:
        # Arrange — bare query is orthogonal to the anchor (fails alone),
        # but "last reply + query" is seeded to match it.
        embedder = _FakeEmbedder(
            {
                "show me this as a table": [0.0, 1.0, 0.0],
                "DAM price forecast for HB_NORTH show me this as a table": [
                    1.0,
                    0.0,
                    0.0,
                ],
            }
        )
        f = ScopeFilter(embedder, threshold=0.5)
        f._anchors = [[1.0, 0.0, 0.0]]
        history: list[ModelRequest | ModelResponse] = [
            ModelResponse(parts=[TextPart(content="DAM price forecast for HB_NORTH")])
        ]

        # Act
        result = await f.in_scope("show me this as a table", message_history=history)

        # Assert — rescued by the context-aided retry
        assert result is True
        assert embedder.calls == [
            "show me this as a table",
            "DAM price forecast for HB_NORTH show me this as a table",
        ]

    async def test_no_history_stays_out_of_scope_after_bare_query_fails(self) -> None:
        # Arrange — bare query fails, nothing to retry with
        embedder = _FakeEmbedder({"off-topic": [0.0, 1.0, 0.0]})
        f = ScopeFilter(embedder, threshold=0.5)
        f._anchors = [[1.0, 0.0, 0.0]]

        # Act
        result = await f.in_scope("off-topic", message_history=None)

        # Assert — no second embed call possible without history
        assert result is False
        assert embedder.calls == ["off-topic"]

    async def test_off_topic_query_does_not_ride_on_a_strong_prior_reply(self) -> None:
        # Arrange — regression: "pizza toppings" got through live because
        # a strong in-domain last reply pulled the BLENDED text above the
        # old equal threshold (0.48), even though the query itself is
        # pure noise. Combined vector lands at cos≈0.55 — passes the old
        # threshold, must fail the production (tightened) default.
        embedder = _FakeEmbedder(
            {
                "what are popular pizza toppings?": [0.0, 1.0, 0.0],
                "DAM price forecast for HB_NORTH what are popular pizza toppings?": [
                    0.55,
                    0.835,
                    0.0,
                ],
            }
        )
        f = ScopeFilter(embedder)  # production defaults, not a test-tuned threshold
        f._anchors = [[1.0, 0.0, 0.0]]
        history: list[ModelRequest | ModelResponse] = [
            ModelResponse(parts=[TextPart(content="DAM price forecast for HB_NORTH")])
        ]

        # Act
        result = await f.in_scope(
            "what are popular pizza toppings?", message_history=history
        )

        # Assert — off-topic stays rejected even with strong context to ride on
        assert result is False

    async def test_last_response_with_no_text_part_skips_the_retry(self) -> None:
        # Arrange — most recent assistant turn was pure tool-call, no prose
        embedder = _FakeEmbedder({"off-topic": [0.0, 1.0, 0.0]})
        f = ScopeFilter(embedder, threshold=0.5)
        f._anchors = [[1.0, 0.0, 0.0]]
        history: list[ModelRequest | ModelResponse] = [
            ModelResponse(
                parts=[
                    ToolCallPart(tool_name="get_forecast", args={}, tool_call_id="1")
                ]
            )
        ]

        # Act
        result = await f.in_scope("off-topic", message_history=history)

        # Assert — nothing text-shaped to build a contextual retry from
        assert result is False
        assert embedder.calls == ["off-topic"]
