"""Unit tests for eval_report rendering + cost math."""

from .eval_report import (
    USD_PER_INPUT_TOK,
    USD_PER_OUTPUT_TOK,
    CaseResult,
    ProviderReport,
    render_cost_projection,
    render_leaderboard,
)


def _case(
    name: str, lat: int, inp: int, out: int, art: list[str], corr: float
) -> CaseResult:
    cost = inp * USD_PER_INPUT_TOK + out * USD_PER_OUTPUT_TOK
    return CaseResult(
        case=name,
        latency_ms=lat,
        input_tokens=inp,
        output_tokens=out,
        artifact_kinds=art,
        correctness=corr,
        cost_usd=cost,
    )


class TestProviderReport:
    def test_aggregates(self) -> None:
        # Arrange
        report = ProviderReport(
            provider="bedrock",
            results=[
                _case("a", 100, 200, 50, ["line"], 1.0),
                _case("b", 300, 100, 25, [], 0.5),
            ],
        )

        # Assert
        assert report.avg_latency_ms == 200.0
        assert report.correctness_rate == 0.75
        assert report.total_cost_usd > 0.0


class TestRenderLeaderboard:
    def test_includes_provider_header_and_totals(self) -> None:
        # Arrange
        report = ProviderReport(
            provider="ollama",
            results=[_case("c1", 500, 50, 10, ["bar"], 1.0)],
        )

        # Act
        md = render_leaderboard([report])

        # Assert
        assert "## ollama" in md
        assert "c1" in md
        assert "Totals" in md
        assert "$0.0" in md  # cost cell formatted


class TestRenderCostProjection:
    def test_projects_three_tiers(self) -> None:
        # Arrange + Act
        md = render_cost_projection(bedrock_avg_cost_per_query=0.01)

        # Assert
        assert "100" in md and "500" in md and "1000" in md
        # 0.01 * 100 * 30 = 30.00
        assert "$30.00" in md
