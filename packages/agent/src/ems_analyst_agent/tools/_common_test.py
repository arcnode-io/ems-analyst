"""Unit tests for the chart→table re-render — pure, no network."""

from ..schemas import AnalystArtifact, TableSpec
from ._common import _to_table

_TS = "2026-01-01T00:00:00Z"


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
