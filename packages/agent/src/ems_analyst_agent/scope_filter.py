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
"""

from __future__ import annotations

import asyncio
import math

from ems_analyst_mcp.clients import Embedder

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


class ScopeFilter:
    """Cosine-similarity gate against in-domain anchor embeddings."""

    def __init__(
        self, embedder: Embedder, threshold: float = _DEFAULT_THRESHOLD
    ) -> None:
        self._embedder = embedder
        self._threshold = threshold
        self._anchors: list[list[float]] | None = None

    async def _ensure_anchors(self) -> None:
        """Lazy-embed the anchor set on first call. Cached for process lifetime."""
        if self._anchors is None:
            self._anchors = list(
                await asyncio.gather(*(self._embedder.embed(a) for a in _ANCHORS))
            )

    async def in_scope(self, query: str) -> bool:
        """True if any anchor's cosine similarity to query >= threshold."""
        await self._ensure_anchors()
        q = await self._embedder.embed(query)
        assert self._anchors is not None  # for ty
        return max(_cosine(q, a) for a in self._anchors) >= self._threshold


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0
