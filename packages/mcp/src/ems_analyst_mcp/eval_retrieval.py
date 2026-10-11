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

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from .clients import GraphitiClient, RAGClient, make_embedder
from .config import load_config
from .eval_golden_cases import GOLDEN_QUERIES, GoldenQuery
from .eval_golden_cases_negative import OUT_OF_CORPUS_QUERIES
from .eval_golden_graph_cases import GRAPH_GOLDEN_QUERIES
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
        query_shape=case.query_shape,
    )


async def _run_graph(client: GraphitiClient, case: GoldenQuery) -> QueryResult:
    """Score all required relationship links, rather than just any related hit."""
    facts = await client.search(case.query, limit=_SEARCH_LIMIT)
    ids = [fact.id for fact in facts]
    expected = list(dict.fromkeys(fact_id for group in case.required_fact_groups for fact_id in group))
    coverage = sum(
        bool(set(group) & set(ids)) for group in case.required_fact_groups
    ) / len(case.required_fact_groups)
    return QueryResult(
        name=case.name,
        category=case.category,
        query=case.query,
        expected_chunk_ids=expected,
        retrieved_ids=ids,
        top1_id=ids[0] if ids else None,
        top1_score=facts[0].score if facts else None,
        reciprocal_rank=reciprocal_rank(ids, expected),
        recall_at_5=recall_at_k(ids, expected, _RECALL_K),
        scorable=True,
        query_shape=case.query_shape,
        required_evidence_coverage=coverage,
    )


async def main(include_graph: bool = False) -> None:
    """Run every golden + out-of-corpus query, write the markdown report."""
    config = load_config()
    embedder = make_embedder(config.settings)
    client = RAGClient.from_env(embedder)

    all_cases = GOLDEN_QUERIES + OUT_OF_CORPUS_QUERIES
    results = [await _run_one(client, case) for case in all_cases]
    if include_graph:
        graph = GraphitiClient.from_config(config)
        try:
            results.extend(
                [await _run_graph(graph, case) for case in GRAPH_GOLDEN_QUERIES]
            )
        finally:
            await graph.close()
    report = RetrievalEvalReport(results=results)

    out_dir = Path("/tmp")  # noqa: S108  # nosec B108
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    out_path = out_dir / f"ems-eval-retrieval-{stamp}.md"
    out_path.write_text(render_report(report), encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"MRR (in-corpus): {report.mean_reciprocal_rank:.3f}")
    print(f"Recall@5 (in-corpus): {report.recall_at_5_rate * 100:.0f}%")
    if include_graph and any(
        r.required_evidence_coverage != 1.0
        for r in results
        if r.query_shape != "flat_lookup"
    ):
        raise SystemExit(
            "graph retrieval gate failed: missing required relationship evidence"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--graph",
        action="store_true",
        help="include scoped graph gates alongside flat RAG",
    )
    asyncio.run(main(include_graph=parser.parse_args().graph))
