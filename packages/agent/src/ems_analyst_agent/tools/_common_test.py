"""Unit tests for the chart→table re-render and the once-per-turn
tool-menu guard — pure, no network.
"""

from dataclasses import dataclass

import pytest
from pydantic_ai.tools import ToolDefinition

from ..schemas import AnalystArtifact, TableSpec
from ._common import _TelemetryDeps, _omit_if_cached, _to_table

_TS = "2026-01-01T00:00:00Z"


@dataclass
class _FakeCtx:
    """Minimal RunContext stand-in — prepare hooks only ever read `.deps`."""

    deps: _TelemetryDeps


def _table_spec(artifact: AnalystArtifact) -> TableSpec:
    """Assert the artifact is a table and hand back its (narrowed) spec."""
    assert artifact.kind == "table"
    spec = artifact.spec
    assert isinstance(spec, TableSpec)
    return spec


def _line() -> AnalystArtifact:
    return AnalystArtifact.model_validate(
        {
            "kind": "line",
            "spec": {
                "title": "SoC",
                "xAxis": {"label": "Time", "kind": "time"},
                "yAxis": {"label": "state_of_charge", "unit": "%"},
                "series": [
                    {
                        "label": "BESS-01",
                        "points": [
                            {"x": "t1", "y": 40.0},
                            {"x": "t2", "y": 55.0},
                        ],
                    }
                ],
                "dataAsOf": _TS,
            },
        }
    )


class TestToTable:
    """AAA — _to_table flattens a chart's data into a TableSpec."""

    def test_line_becomes_table_of_points(self) -> None:
        # Act
        spec = _table_spec(_to_table(_line()))

        # Assert
        assert [c.key for c in spec.columns] == ["time", "value"]
        assert len(spec.rows) == 2
        assert spec.rows[0] == {"time": "t1", "value": 40.0}

    def test_bar_becomes_table_of_categories(self) -> None:
        # Arrange
        bar = AnalystArtifact.model_validate(
            {
                "kind": "bar",
                "spec": {
                    "title": "Revenue",
                    "xAxis": {"label": "Market", "categories": ["DAM", "RTM"]},
                    "yAxis": {"label": "Revenue", "unit": "USD"},
                    "series": [{"label": "Revenue", "values": [150.0, 90.0]}],
                    "dataAsOf": _TS,
                },
            }
        )

        # Act
        spec = _table_spec(_to_table(bar))

        # Assert
        assert spec.rows == [
            {"category": "DAM", "value": 150.0},
            {"category": "RTM", "value": 90.0},
        ]

    def test_error_artifact_passes_through(self) -> None:
        # Arrange
        err = AnalystArtifact.model_validate(
            {
                "kind": "error",
                "spec": {"code": "not_found", "message": "x", "dataAsOf": _TS},
            }
        )

        # Act + Assert — nothing to tabulate
        assert _to_table(err).kind == "error"


class TestOmitIfCached:
    """AAA — the prepare hook pulls a tool off the menu once it's cached.

    describe_site / get_topology already skip the refetch on a cache
    hit, but pydantic-ai's tool_calls_limit is charged on every call the
    model *requests*, before the tool body runs — a fast cache hit still
    burns a budget slot. This hook stops the model from asking a second
    time at all.
    """

    @pytest.mark.asyncio
    async def test_offers_tool_when_cache_empty(self) -> None:
        # Arrange
        prepare = _omit_if_cached("topology_cache")
        ctx = _FakeCtx(deps=_TelemetryDeps())
        tool_def = ToolDefinition(name="get_topology")

        # Act
        result = await prepare(ctx, tool_def)  # ty: ignore[invalid-argument-type]

        # Assert
        assert result is tool_def

    @pytest.mark.asyncio
    async def test_omits_tool_once_cache_is_set(self) -> None:
        # Arrange
        prepare = _omit_if_cached("topology_cache")
        deps = _TelemetryDeps()
        deps.topology_cache = AnalystArtifact.model_validate(
            {
                "kind": "error",
                "spec": {"code": "not_found", "message": "x", "dataAsOf": _TS},
            }
        )
        ctx = _FakeCtx(deps=deps)
        tool_def = ToolDefinition(name="get_topology")

        # Act
        result = await prepare(ctx, tool_def)  # ty: ignore[invalid-argument-type]

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_different_cache_attrs_are_independent(self) -> None:
        # Arrange — site_description_cache set, topology_cache untouched
        deps = _TelemetryDeps()
        deps.site_description_cache = AnalystArtifact.model_validate(
            {
                "kind": "error",
                "spec": {"code": "not_found", "message": "x", "dataAsOf": _TS},
            }
        )
        ctx = _FakeCtx(deps=deps)
        topology_tool_def = ToolDefinition(name="get_topology")

        # Act
        result = await _omit_if_cached("topology_cache")(
            ctx,  # ty: ignore[invalid-argument-type]
            topology_tool_def,
        )

        # Assert — unrelated cache attr being set doesn't hide this tool
        assert result is topology_tool_def
