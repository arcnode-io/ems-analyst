"""Report shapes + markdown rendering for the golden retrieval eval.

Mirrors ems_analyst_agent.eval_report's split (dataclasses + a pure
render function, no network calls) for symmetry within the monorepo.
"""

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class QueryResult:
    """One golden query's outcome against the live knowledge table.

    `scorable` is False for out-of-corpus cases (expected_chunk_ids=[]) —
    recall/MRR are mechanically 0.0 for them either way, but that 0.0
    doesn't mean anything yet (no confidence threshold exists to say
    "correctly rejected" vs "randomly missed"), so aggregates exclude them.
    """

    name: str
    category: str
    query: str
    expected_chunk_ids: list[str]
    retrieved_ids: list[str]
    top1_id: str | None
    top1_score: float | None
    reciprocal_rank: float
    recall_at_5: float
    scorable: bool


@dataclass
class RetrievalEvalReport:
    """All golden-query results from one eval run."""

    results: list[QueryResult]

    @property
    def scorable_results(self) -> list[QueryResult]:
        """In-corpus cases only — the ones recall@5/MRR mean something for."""
        return [r for r in self.results if r.scorable]

    @property
    def mean_reciprocal_rank(self) -> float:
        """Mean reciprocal rank over scorable (in-corpus) results only."""
        scorable = self.scorable_results
        return sum(r.reciprocal_rank for r in scorable) / max(len(scorable), 1)

    @property
    def recall_at_5_rate(self) -> float:
        """Fraction of scorable (in-corpus) results with a top-5 hit."""
        scorable = self.scorable_results
        return sum(r.recall_at_5 for r in scorable) / max(len(scorable), 1)


def render_report(report: RetrievalEvalReport) -> str:
    """Markdown: summary stats, per-category breakdown, out-of-corpus capture."""
    lines: list[str] = [
        f"# Domain MCP retrieval eval — {datetime.now(UTC).strftime('%Y-%m-%d %H:%MZ')}",
        "",
        f"**MRR (in-corpus, n={len(report.scorable_results)}): "
        f"{report.mean_reciprocal_rank:.3f}**  ",
        f"**Recall@5 (in-corpus): {report.recall_at_5_rate * 100:.0f}%**",
        "",
        "## In-corpus queries",
        "",
        "| Category | Query | Expected | Top-1 | RR | Recall@5 |",
        "|---|---|---|---|---:|---:|",
    ]
    lines.extend(
        f"| {r.category} | {r.name} | {','.join(r.expected_chunk_ids)} "
        f"| {r.top1_id or '—'} | {r.reciprocal_rank:.2f} | {r.recall_at_5:.0f} |"
        for r in report.scorable_results
    )
    lines += [
        "",
        "## Out-of-corpus queries (not yet scorable — see handoff §1)",
        "",
        "_No confidence threshold exists yet (vector_score isn't surfaced), "
        "so these are captured for visibility only, not scored pass/fail._",
        "",
        "| Category | Query | Top-1 result | Top-1 fused score |",
        "|---|---|---|---:|",
    ]
    lines.extend(
        f"| {r.category} | {r.name} | {r.top1_id or '—'} | {_fmt_score(r.top1_score)} |"
        for r in report.results
        if not r.scorable
    )
    return "\n".join(lines) + "\n"


def _fmt_score(score: float | None) -> str:
    """5-decimal score, or an em-dash for a query with no results at all."""
    return f"{score:.5f}" if score is not None else "—"
