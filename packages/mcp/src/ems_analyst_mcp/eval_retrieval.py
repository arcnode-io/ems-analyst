"""Golden retrieval eval — runs GOLDEN_QUERIES against the live RAGClient.

Reads the same env RAGClient/embedder read in production (VECTOR_URL,
ENV + Ollama/Bedrock settings via cfg.defaults.yml) — run it the way you'd
run the real service, e.g. inside the deployed container so it sees the
real VECTOR_URL:

    docker exec -i ems-analyst-server /app/.venv/bin/python \\
        -m ems_analyst_mcp.eval_retrieval

Writes /tmp/ems-eval-retrieval-{date}.md — see eval_retrieval_report.py
for the shape.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from .clients import RAGClient, make_embedder
from .config import load_config
from .eval_golden_cases import GOLDEN_QUERIES, GoldenQuery
from .eval_golden_cases_negative import OUT_OF_CORPUS_QUERIES
from .eval_retrieval_report import QueryResult, RetrievalEvalReport, render_report
from .eval_retrieval_scoring import recall_at_k, reciprocal_rank

_RECALL_K: int = 5
_SEARCH_LIMIT: int = 10


async def _run_one(client: RAGClient, case: GoldenQuery) -> QueryResult:
    """Run one golden query against the live table, score it."""
    docs = await client.search(case.query, limit=_SEARCH_LIMIT)
    retrieved_ids = [d.id for d in docs]
    scorable = bool(case.expected_chunk_ids)
    return QueryResult(
        name=case.name,
        category=case.category,
        query=case.query,
        expected_chunk_ids=case.expected_chunk_ids,
        retrieved_ids=retrieved_ids,
        top1_id=retrieved_ids[0] if retrieved_ids else None,
        top1_score=docs[0].similarity_score if docs else None,
        reciprocal_rank=reciprocal_rank(retrieved_ids, case.expected_chunk_ids),
        recall_at_5=recall_at_k(retrieved_ids, case.expected_chunk_ids, _RECALL_K),
        scorable=scorable,
    )


async def main() -> None:
    """Run every golden + out-of-corpus query, write the markdown report."""
    config = load_config()
    embedder = make_embedder(config.settings)
    client = RAGClient.from_env(embedder)

    all_cases = GOLDEN_QUERIES + OUT_OF_CORPUS_QUERIES
    results = [await _run_one(client, case) for case in all_cases]
    report = RetrievalEvalReport(results=results)

    out_dir = Path("/tmp")  # noqa: S108  # nosec B108
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    out_path = out_dir / f"ems-eval-retrieval-{stamp}.md"
    out_path.write_text(render_report(report), encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"MRR (in-corpus): {report.mean_reciprocal_rank:.3f}")
    print(f"Recall@5 (in-corpus): {report.recall_at_5_rate * 100:.0f}%")


if __name__ == "__main__":
    asyncio.run(main())
