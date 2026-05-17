"""Tests for the analyst render-spec contract.

These models are the HMI integration boundary — see
/tmp/HANDOFF-analyst-backend.md. Tests focus on:
- discriminated-union routing on `kind`
- round-trip JSON to catch contract drift
"""

import json

from .schemas import (
    AnalystArtifact,
    AnalystMessage,
    BarSpec,
    LineSpec,
    PieSpec,
    TableSpec,
    ToolError,
)


class TestLineSpec:
    """AAA round-trip + nullable y."""

    def test_round_trip_with_threshold(self) -> None:
        # Arrange
        original = LineSpec.model_validate(
            {
                "title": "BESS-01 State of Charge",
                "xAxis": {"label": "Time", "kind": "time"},
                "yAxis": {"label": "SoC", "unit": "%"},
                "series": [
                    {
                        "label": "BESS-01",
                        "points": [
                            {"x": "2026-05-16T00:00:00Z", "y": 87.4},
                            {"x": "2026-05-16T01:00:00Z", "y": None},
                        ],
                    }
                ],
                "thresholds": [
                    {"label": "low_soc_warn", "y": 20.0, "severity": "warn"}
                ],
                "dataAsOf": "2026-05-16T01:00:00Z",
            }
        )

        # Act
        re_parsed = LineSpec.model_validate_json(original.model_dump_json(by_alias=True))

        # Assert
        assert re_parsed == original
        assert re_parsed.series[0].points[1].y is None


class TestArtifactDiscriminator:
    """AAA — kind discriminator routes to the right variant."""

    def test_routes_bar_kind(self) -> None:
        # Arrange
        payload = {
            "kind": "bar",
            "spec": {
                "title": "Today's revenue by market",
                "xAxis": {"label": "Market", "categories": ["DAM", "RTM", "FREQ"]},
                "yAxis": {"label": "Revenue", "unit": "USD"},
                "series": [{"label": "site_1", "values": [1234.5, 678.9, 234.1]}],
                "dataAsOf": "2026-05-16T12:00:00Z",
            },
        }

        # Act
        artifact = AnalystArtifact.model_validate(payload)

        # Assert
        assert artifact.kind == "bar"
        assert isinstance(artifact.spec, BarSpec)
        assert artifact.spec.series[0].values == [1234.5, 678.9, 234.1]

    def test_routes_error_kind(self) -> None:
        # Arrange
        payload = {
            "kind": "error",
            "spec": {
                "code": "not_found",
                "message": "Device BESS-99 not found",
                "dataAsOf": "2026-05-16T12:00:00Z",
            },
        }

        # Act
        artifact = AnalystArtifact.model_validate(payload)

        # Assert
        assert artifact.kind == "error"
        assert isinstance(artifact.spec, ToolError)
        assert artifact.spec.code == "not_found"


class TestAnalystMessage:
    """AAA — interleaved text + artifact content."""

    def test_interleaved_text_and_artifact(self) -> None:
        # Arrange
        msg = AnalystMessage(
            role="assistant",
            content=[
                {"type": "text", "text": "BESS-01 SoC trended down."},
                {
                    "type": "artifact",
                    "artifact": {
                        "kind": "pie",
                        "spec": {
                            "title": "Energy by source",
                            "unit": "MWh",
                            "slices": [
                                {"label": "solar", "value": 120.5},
                                {"label": "wind", "value": 88.2},
                            ],
                            "dataAsOf": "2026-05-16T12:00:00Z",
                        },
                    },
                },
            ],
        )

        # Act
        serialized = json.loads(msg.model_dump_json(by_alias=True))

        # Assert
        assert serialized["role"] == "assistant"
        assert serialized["content"][0]["type"] == "text"
        assert serialized["content"][1]["type"] == "artifact"
        assert serialized["content"][1]["artifact"]["kind"] == "pie"


class TestTableSpec:
    """AAA — row severity + heterogeneous row values."""

    def test_round_trip_with_severity(self) -> None:
        # Arrange
        spec = TableSpec(
            title="Devices in alarm",
            columns=[
                {"key": "device", "label": "Device"},
                {"key": "soc", "label": "SoC", "align": "right", "unit": "%"},
            ],
            rows=[
                {"device": "BESS-01", "soc": 12.3},
                {"device": "BESS-03", "soc": None},
            ],
            rowSeverity=["alarm", None],
            dataAsOf="2026-05-16T12:00:00Z",
        )

        # Act
        re_parsed = TableSpec.model_validate_json(spec.model_dump_json(by_alias=True))

        # Assert
        assert re_parsed == spec
        assert re_parsed.row_severity == ["alarm", None]


class TestPieSpec:
    """AAA — pie slices preserved."""

    def test_round_trip(self) -> None:
        # Arrange
        spec = PieSpec(
            title="Energy",
            unit="MWh",
            slices=[
                {"label": "solar", "value": 120.5},
                {"label": "wind", "value": 88.2},
            ],
            dataAsOf="2026-05-16T12:00:00Z",
        )

        # Act
        re_parsed = PieSpec.model_validate_json(spec.model_dump_json(by_alias=True))

        # Assert
        assert re_parsed == spec
