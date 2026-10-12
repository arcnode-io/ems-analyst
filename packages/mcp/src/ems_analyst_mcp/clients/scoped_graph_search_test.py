"""Scoped retrieval must preserve evidence budgets without embedding the graph."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from graphiti_core import Graphiti
from graphiti_core.search.search_config import EdgeSearchMethod

from .scoped_graph_search import search_scoped


@pytest.mark.asyncio
async def test_standard_search_scopes_to_family_and_never_uses_embeddings() -> None:
    """Numeric standard IDs must not retrieve unrelated BESS or other CIP facts."""
    graphiti = SimpleNamespace(
        search_=AsyncMock(return_value=SimpleNamespace(edges=[]))
    )
    await search_scoped(cast(Graphiti, graphiti), "What replaced cip-006-7?", 5, None)
    call = graphiti.search_.call_args.kwargs
    assert call["group_ids"] == ["supersession_CIP-006"]
    assert call["config"].limit == 5
    assert (
        EdgeSearchMethod.cosine_similarity
        not in call["config"].edge_config.search_methods
    )


@pytest.mark.asyncio
async def test_long_chain_retains_each_link_before_redundant_evidence() -> None:
    """A repeated popular link cannot crowd out the other links or exceed limit."""
    alarm = SimpleNamespace(uuid="alarm")
    ppc = SimpleNamespace(uuid="ppc")
    fleet = SimpleNamespace(uuid="fleet")
    detail = SimpleNamespace(uuid="detail")
    graphiti = SimpleNamespace(
        search_=AsyncMock(
            side_effect=[
                SimpleNamespace(edges=[alarm, detail]),
                SimpleNamespace(edges=[ppc]),
                SimpleNamespace(edges=[ppc]),
                SimpleNamespace(edges=[fleet]),
                SimpleNamespace(edges=[ppc, detail]),
            ]
        )
    )
    results = await search_scoped(
        cast(Graphiti, graphiti), "BMS EMS PPC SCADA fleet controls", 3, None
    )
    assert [edge.uuid for edge in results] == ["alarm", "ppc", "fleet"]


@pytest.mark.asyncio
async def test_zero_limit_does_not_query_backend() -> None:
    """Invalid evidence budgets cannot accidentally return a full Graphiti result."""
    graphiti = SimpleNamespace(search_=AsyncMock())
    assert await search_scoped(cast(Graphiti, graphiti), "CIP-006-7", 0, None) == []
    graphiti.search_.assert_not_called()
