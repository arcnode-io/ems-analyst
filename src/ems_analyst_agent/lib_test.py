"""Unit tests for lib helpers — pure functions, no Agent / network."""

from .lib import _presentable
from .schemas import AnalystArtifact

_TS = "2026-01-01T00:00:00Z"


def _table(title: str) -> AnalystArtifact:
    return AnalystArtifact.model_validate(
        {
            "kind": "table",
            "spec": {"title": title, "columns": [], "rows": [], "dataAsOf": _TS},
        }
    )


def _line(title: str) -> AnalystArtifact:
    return AnalystArtifact.model_validate(
        {
            "kind": "line",
            "spec": {
                "title": title,
                "xAxis": {"label": "t", "kind": "time"},
                "yAxis": {"label": "v", "unit": "x"},
                "series": [],
                "dataAsOf": _TS,
            },
        }
    )


class TestPresentable:
    """AAA — _presentable dedupes + drops scaffolding tables."""

    def test_drops_discovery_tables_when_a_chart_exists(self) -> None:
        # Arrange — agent used describe_site + get_topology, then charted
        arts = [_table("Queryable measurements"), _table("Site topology"), _line("SoC")]

        # Act
        kept = _presentable(arts)

        # Assert — only the chart the user asked for survives
        assert [a.kind for a in kept] == ["line"]

    def test_keeps_tables_when_no_chart(self) -> None:
        # Arrange — a genuine "what's on site" turn, no chart produced
        arts = [_table("Site topology")]

        # Act
        kept = _presentable(arts)

        # Assert — the table is the answer here, keep it
        assert [a.kind for a in kept] == ["table"]

    def test_dedupes_repeated_artifacts(self) -> None:
        # Arrange — a loopy turn re-ran the same query
        arts = [_line("SoC"), _line("SoC"), _line("SoC")]

        # Act
        kept = _presentable(arts)

        # Assert
        assert len(kept) == 1
