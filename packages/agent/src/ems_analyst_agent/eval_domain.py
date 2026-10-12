"""Run local-model answer-quality gates through real MCP stdio and seeded DBs.

Requires GRAPH_URL, VECTOR_URL and a configured Neo4j backend. Never spawns
empty databases and never changes a seed. The caller supplies isolated DBs.
Run: python -m ems_analyst_agent.eval_domain --model qwen3.6:27b
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
import tempfile
from typing import TypedDict
from pathlib import Path

from fastmcp.client.transports import StdioTransport
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .eval_domain_cases import DOMAIN_CASES, DomainCase
from .prompts import load_system_prompt


class DomainResult(TypedDict):
    """Serializable result retaining answer, evidence, and independent gates."""

    name: str
    query_shape: str
    answer: str
    calls: list[str]
    evidence: str
    seconds: float
    answer_correct: bool
    evidence_grounded: bool
    retrieval_path_correct: bool
    passed: bool


def score_answer(
    case: DomainCase, answer: str, calls: list[str], evidence: str
) -> dict[str, bool]:
    """Require answer concepts, matching returned evidence, and the right path."""
    expected_tools = (
        {"rag_search"}
        if case.query_shape == "flat_lookup"
        else {"search_knowledge", "verify_fact", "combined_search"}
    )
    return {
        "answer_correct": all(
            re.search(pattern, answer, re.IGNORECASE)
            for pattern in case.answer_patterns
        ),
        "evidence_grounded": all(
            re.search(pattern, evidence, re.IGNORECASE)
            for pattern in case.answer_patterns
        ),
        "retrieval_path_correct": bool(set(calls) & expected_tools),
    }


def _resume_results(output: Path, model_name: str) -> list[DomainResult]:
    saved = output / "agent-results.json"
    if not saved.exists():
        return []
    previous = json.loads(saved.read_text())
    if previous["model"] != model_name:
        raise ValueError(
            "evaluation output belongs to another model; choose a new output directory"
        )
    results: list[DomainResult] = previous["results"]
    for row in results:
        if "passed" not in row:
            row["passed"] = bool(row.get("pass", False))
    return results


async def run(model_name: str, base_url: str, output: Path) -> None:
    """Evaluate sequentially so a shared local model is not overloaded."""
    if not os.environ.get("GRAPH_URL") or not os.environ.get("VECTOR_URL"):
        raise RuntimeError(
            "GRAPH_URL and VECTOR_URL must point at seeded evaluation databases"
        )
    toolset = MCPToolset(
        StdioTransport(
            command=sys.executable,
            args=["-m", "ems_analyst_mcp"],
            env=os.environ.copy(),
        ),
        init_timeout=60,
    )
    model = OpenAIChatModel(
        model_name, provider=OpenAIProvider(base_url=base_url, api_key="ollama")
    )
    agent = Agent(model, toolsets=[toolset], system_prompt=load_system_prompt())
    results: list[DomainResult] = []
    output.mkdir(parents=True, exist_ok=True)
    results = _resume_results(output, model_name)
    completed = {row["name"] for row in results}
    async with agent:
        for case in DOMAIN_CASES:
            if case.name in completed:
                continue
            started = time.monotonic()
            result = await agent.run(case.prompt)
            messages = result.all_messages()
            calls = [
                part.tool_name
                for message in messages
                if isinstance(message, ModelResponse)
                for part in message.parts
                if isinstance(part, ToolCallPart)
            ]
            evidence = "\n".join(
                str(part.content)
                for message in messages
                for part in message.parts
                if isinstance(part, ToolReturnPart)
            )
            score = score_answer(case, str(result.output), calls, evidence)
            row: DomainResult = {
                "name": case.name,
                "query_shape": case.query_shape,
                "answer": str(result.output),
                "calls": calls,
                "evidence": evidence,
                "seconds": round(time.monotonic() - started, 1),
                "answer_correct": score["answer_correct"],
                "evidence_grounded": score["evidence_grounded"],
                "retrieval_path_correct": score["retrieval_path_correct"],
                "passed": all(score.values()),
            }
            results.append(row)
            (output / "agent-results.json").write_text(
                json.dumps({"model": model_name, "results": results}, indent=2)
            )
            print(f"{case.name}: {score}, {row['seconds']}s, calls={calls}", flush=True)
    lines = [
        f"# Domain MCP scoped-graph evaluation ({model_name})",
        "",
        "| Shape | N | Answers | Grounded evidence | Correct retrieval path |",
        "|---|---:|---:|---:|---:|",
    ]
    for shape in sorted({row["query_shape"] for row in results}):
        rows = [row for row in results if row["query_shape"] == shape]
        lines.append(
            f"| {shape} | {len(rows)} | {sum(row['answer_correct'] for row in rows)}/{len(rows)} | {sum(row['evidence_grounded'] for row in rows)}/{len(rows)} | {sum(row['retrieval_path_correct'] for row in rows)}/{len(rows)} |"
        )
    for row in results:
        lines.extend(
            [
                "",
                f"## {row['name']}",
                "",
                f"Tools: {', '.join(row['calls'])}",
                "",
                row["answer"],
            ]
        )
    (output / "agent-report.md").write_text("\n".join(lines) + "\n")
    if not all(row["passed"] for row in results):
        raise SystemExit("domain MCP gate failed; see agent-results.json")


def main() -> None:
    """CLI for a local model against caller-provided seeded databases."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3.6:27b")
    parser.add_argument("--base-url", default="http://173.211.12.43:11434/v1")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or Path(tempfile.mkdtemp(prefix="ems-domain-eval-"))
    asyncio.run(run(args.model, args.base_url, output))


if __name__ == "__main__":
    main()
