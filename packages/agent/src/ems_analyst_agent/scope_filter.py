"""Pre-gate filter — embed user query, refuse if not close to any in-domain anchor.

Runs BEFORE the main agent turn. An off-domain query (cooking, sports,
generic coding) is rejected with a canned refusal in ~1s, saving the
gemma4:26b 15s/turn cost on irrelevant input.

The anchor set covers the analyst's actual domain — power markets,
BESS, grid protocols, weather → demand, regulatory, device status.
Threshold empirically tuned against the live qwen3-embedding:4b
endpoint (2026-09-04): off-domain queries ("implement fibonacci",
"capital of France") scored 0.25-0.45 against the original anchor
set — 0.30 let them through. 0.48 sits above that noise floor and
below the lowest in-domain score observed (0.53).

A bare query that fails gets one retry with the last assistant reply
folded in — a short follow-up ("show me this as a table") often has no
domain vocabulary of its own but is clearly in-scope given what was
just discussed. Caught live (2026-10-11): an equal threshold let a
genuinely off-domain query ("what are popular pizza toppings?") ride
through on a strong in-domain prior reply — blending pulls the combined
embedding toward whichever side is more semantically dense, not
necessarily toward relevance. _CONTEXT_THRESHOLD is deliberately set
above _DEFAULT_THRESHOLD's single-message in-domain floor (0.53) to
compensate: the blended text has to look at least as domain-focused as
a real on-topic message would, not just limp past the bare-query bar.
Still not independently probed against real traffic on this longer
input shape — tune it with real data before trusting it the way
_DEFAULT_THRESHOLD is trusted; err toward stricter until then.
"""

from __future__ import annotations

import asyncio
import math

from ems_analyst_mcp.clients import Embedder
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart

# 20 prompts spanning the agent's intended scope. Embedded once at
# first in_scope call; max cosine vs the query embedding >= threshold
# means in-scope.
_ANCHORS: tuple[str, ...] = (
    "What's the DAM LMP forecast for next 24 hours at HB_NORTH",
    "Show me ERCOT real-time pricing",
    "BESS state of charge over the last 24 hours",
    "Compare revenue across DAM and RTM markets",
    "Energy mix breakdown by source",
    "Explain Modbus function code 3",
    "What does NERC CIP-002 require for BES Cyber Systems",
    "DNP3 protocol overview",
    "Load forecast for the ERCOT north zone",
    "Solar curtailment trends in California",
    "How does thermal runaway happen in lithium-ion batteries",
    "Weather impact on grid demand",
    "Inverter clipping behavior at solar PV plants",
    "BESS dispatch arbitrage strategy",
    "What's the wholesale settlement point HB_NORTH",
    "SCADA system architecture for substations",
    "Recent energy news headlines",
    "Grid frequency regulation",
    "Power factor correction",
    "Battery degradation curves",
    "Which devices are currently in alarm or fault state",
    "Check equipment status across the site",
)

# Empirically tuned against qwen3-embedding:4b — see module docstring.
_DEFAULT_THRESHOLD: float = 0.48

# See module docstring — deliberately stricter than _DEFAULT_THRESHOLD,
# not yet independently probed.
_CONTEXT_THRESHOLD: float = 0.60


class ScopeFilter:
    """Cosine-similarity gate against in-domain anchor embeddings."""

    def __init__(
        self,
        embedder: Embedder,
        threshold: float = _DEFAULT_THRESHOLD,
        context_threshold: float = _CONTEXT_THRESHOLD,
    ) -> None:
        self._embedder = embedder
        self._threshold = threshold
        self._context_threshold = context_threshold
        self._anchors: list[list[float]] | None = None

    async def _ensure_anchors(self) -> None:
        """Lazy-embed the anchor set on first call. Cached for process lifetime."""
        if self._anchors is None:
            self._anchors = list(
                await asyncio.gather(*(self._embedder.embed(a) for a in _ANCHORS))
            )

    async def _max_cosine(self, text: str) -> float:
        """Embed `text`, return its highest cosine similarity against any anchor."""
        assert self._anchors is not None  # for ty — _ensure_anchors already ran
        vec = await self._embedder.embed(text)
        return max(_cosine(vec, a) for a in self._anchors)

    async def in_scope(
        self, query: str, message_history: list[ModelMessage] | None = None
    ) -> bool:
        """True if `query` alone, or `query` with recent context, scores in-domain.

        Fast path (today's cost, unchanged): the bare query alone. Only a
        failing bare query pays for a second embed call — and only when
        there's a prior assistant reply to fold in; a fresh first message
        has nothing to retry with.
        """
        await self._ensure_anchors()
        if await self._max_cosine(query) >= self._threshold:
            return True
        last_reply = _last_assistant_text(message_history) if message_history else None
        if not last_reply:
            return False
        return (
            await self._max_cosine(f"{last_reply} {query}") >= self._context_threshold
        )


def _last_assistant_text(history: list[ModelMessage]) -> str | None:
    """Text from the most recent assistant turn's TextPart(s), if any.

    Walks backward since the last entry isn't always a ModelResponse
    (and a tool-call-only response carries no TextPart at all) — skip
    past those rather than treating "no text here" as "no context at all".
    """
    for msg in reversed(history):
        if not isinstance(msg, ModelResponse):
            continue
        texts = [p.content for p in msg.parts if isinstance(p, TextPart)]
        if texts:
            return " ".join(texts)
    return None


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0
