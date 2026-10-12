"""Lexical seeds plus traversal for the two ADR-026 relationship shapes."""

import asyncio
import re
from itertools import zip_longest

from graphiti_core import Graphiti
from graphiti_core.edges import EntityEdge
from graphiti_core.search.search_config import (
    EdgeReranker,
    EdgeSearchConfig,
    EdgeSearchMethod,
    SearchConfig,
)


def link_queries(query: str) -> list[str]:
    """Give each named control-chain link a chance in the evidence budget.

    A broad hierarchy query otherwise fills its top ten with PPC/SCADA
    variations and vendor mentions, omitting the BMS and fleet endpoints.
    These are query decompositions, not generated or asserted facts.
    """
    normalized = query.lower()
    aliases = {
        "battery management system": "bms",
        "energy management system": "ems",
        "power plant controller": "ppc",
        "supervisory control and data acquisition": "scada",
    }
    for phrase, acronym in aliases.items():
        normalized = normalized.replace(phrase, acronym)
    words = set(re.findall(r"\b\w+\b", normalized))
    links = [("bms", "ems"), ("ems", "ppc"), ("ppc", "scada")]
    queries = [f"{left} {right}" for left, right in links if {left, right} <= words]
    if "fleet" in words and queries:
        queries.append("fleet controls coordinated response")
    return queries if len(queries) > 1 else []


async def search_scoped(
    graphiti: Graphiti, query: str, limit: int, center_node_uuid: str | None
) -> list[EntityEdge]:
    """Retrieve named chain links fairly, then fill with lexical/traversal facts."""
    if limit <= 0:
        return []
    stems = re.findall(r"\bCIP-\d{3}\b", query, re.IGNORECASE)
    groups = sorted({f"supersession_{stem.upper()}" for stem in stems}) or None

    async def run(text: str, traverse: bool) -> list[EntityEdge]:
        methods = [EdgeSearchMethod.bm25]
        if traverse:
            methods.append(EdgeSearchMethod.bfs)
        results = await graphiti.search_(
            query=text,
            group_ids=groups,
            center_node_uuid=center_node_uuid,
            config=SearchConfig(
                edge_config=EdgeSearchConfig(
                    search_methods=methods, reranker=EdgeReranker.rrf, bfs_max_depth=3
                ),
                limit=limit,
            ),
        )
        return results.edges

    rankings = await asyncio.gather(
        *(run(text, False) for text in link_queries(query)), run(query, True)
    )
    seen: set[str] = set()
    merged: list[EntityEdge] = []
    for row in zip_longest(*rankings):
        for edge in row:
            if edge is not None and edge.uuid not in seen:
                merged.append(edge)
                seen.add(edge.uuid)
                if len(merged) == limit:
                    return merged
    return merged
