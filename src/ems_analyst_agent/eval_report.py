"""Eval reporting + cost helpers.

Split from eval.py to stay under the 200-line cap. Pure data shapes +
markdown rendering — no network calls, no model loads.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

# Bedrock Sonnet 4.6 (us.* CRIS): $3/MTok in, $15/MTok out + ~10% CRIS surcharge.
USD_PER_INPUT_TOK: float = 3.30 / 1_000_000
USD_PER_OUTPUT_TOK: float = 16.50 / 1_000_000

Provider = Literal["ollama", "bedrock"]


@dataclass
class CaseResult:
    """Per-case metrics from one provider run."""

    case: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    artifact_kinds: list[str]
    correctness: float  # 0..1
    cost_usd: float


@dataclass
class ProviderReport:
    """All cases run against one provider."""

    provider: Provider
    results: list[CaseResult]

    @property
    def total_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.results)

    @property
    def avg_latency_ms(self) -> float:
        return sum(r.latency_ms for r in self.results) / max(len(self.results), 1)

    @property
    def correctness_rate(self) -> float:
        return sum(r.correctness for r in self.results) / max(len(self.results), 1)


def render_leaderboard(reports: list[ProviderReport]) -> str:
    """Markdown leaderboard — one section per provider + totals."""
    lines: list[str] = [
        f"# Analyst eval leaderboard — {datetime.now(UTC).strftime('%Y-%m-%d %H:%MZ')}",
        "",
    ]
    for rep in reports:
        lines.append(f"## {rep.provider}")
        lines.append("")
        lines.append("| Case | latency_ms | in_tok | out_tok | artifacts | correct | $$ |")
        lines.append("|---|---:|---:|---:|---|---:|---:|")
        for r in rep.results:
            lines.append(
                f"| {r.case} | {r.latency_ms} | {r.input_tokens} | {r.output_tokens} "
                f"| {','.join(r.artifact_kinds) or '—'} | {r.correctness:.2f} "
                f"| ${r.cost_usd:.5f} |"
            )
        lines.append("")
        lines.append(
            f"**Totals — avg latency {rep.avg_latency_ms:.0f} ms · "
            f"correctness {rep.correctness_rate * 100:.0f}% · "
            f"cost ${rep.total_cost_usd:.4f}**"
        )
        lines.append("")
    return "\n".join(lines)


def render_cost_projection(bedrock_avg_cost_per_query: float) -> str:
    """Forecast monthly Bedrock burn at 100/500/1000 queries/day."""
    lines = [
        "# Anthropic / Bedrock cost projection",
        "",
        f"Per-query average cost (from tonight's eval): "
        f"**${bedrock_avg_cost_per_query:.4f}**",
        "",
        "| Queries/day | Monthly burn (30d) | Yearly burn |",
        "|---:|---:|---:|",
    ]
    for qpd in (100, 500, 1000):
        monthly = bedrock_avg_cost_per_query * qpd * 30
        yearly = monthly * 12
        lines.append(f"| {qpd} | ${monthly:.2f} | ${yearly:.0f} |")
    lines.append("")
    lines.append(
        "Recommendation: buy AWS credit equal to ~3 months of your expected "
        "QPD tier. Trim with prompt caching (90% cache discount) once "
        "system prompt stabilizes."
    )
    return "\n".join(lines)
