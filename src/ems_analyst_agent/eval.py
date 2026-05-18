"""Side-by-side eval harness — Ollama vs Bedrock on the analyst surface.

Strict serial — never load two models concurrently. See
[[project-eval-budget]]: Bedrock cap ~$5/session, Ollama appliance
melts under parallel model loads.

Run:
    python -m ems_analyst_agent.eval  # writes leaderboard + cost md to /tmp

Reporting + cost math lives in eval_report.py.
"""

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic_ai import Agent as PydanticAgent, Tool
from pydantic_ai.models import Model
from pydantic_ai.models.bedrock import BedrockConverseModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .eval_report import (
    USD_PER_INPUT_TOK,
    USD_PER_OUTPUT_TOK,
    CaseResult,
    Provider,
    ProviderReport,
    render_cost_projection,
    render_leaderboard,
)
from .eval_seed import EVAL_SITE_ID, EvalServerClient, seeded_server_client
from .prompts import load_system_prompt
from .tools.telemetry import _TelemetryDeps
from .tools.telemetry_tools import (
    list_devices_where,
    query_energy_breakdown,
    query_markets,
    query_timeseries,
)


@dataclass
class EvalCase:
    """One prompt with its expected artifact kind + keyword."""

    name: str
    prompt: str
    expect_artifact: str | None  # "line"|"bar"|"table"|"pie" or None for text-only
    expect_keyword: str  # lowercased substring expected in the reply


CASES: list[EvalCase] = [
    EvalCase(
        name="list_devices_alarm",
        prompt="List the devices currently in alarm.",
        expect_artifact="table",
        expect_keyword="bess-01",
    ),
    EvalCase(
        name="bess_soc_24h",
        prompt="Show me a line chart of BESS-01 state of charge over the last 24 hours.",
        expect_artifact="line",
        expect_keyword="bess-01",
    ),
    EvalCase(
        name="market_revenue_today",
        prompt="What was today's grid revenue by market?",
        expect_artifact="bar",
        expect_keyword="market",
    ),
    EvalCase(
        name="energy_breakdown",
        prompt="Give me a breakdown of today's energy consumption by source.",
        expect_artifact="pie",
        expect_keyword="energy",
    ),
]


def _build_model(provider: Provider) -> Model:
    """Build a pydantic-ai Model for the given provider. Read-only."""
    if provider == "bedrock":
        return BedrockConverseModel("us.anthropic.claude-sonnet-4-6")
    return OpenAIChatModel(
        "qwen3.6:35b",
        provider=OpenAIProvider(
            base_url="http://173.211.12.43:11434/v1", api_key="ollama"
        ),
    )


def _build_eval_agent(provider: Provider) -> PydanticAgent[object]:
    """Slim Agent — analyst tools + system prompt, NO memory/MCP.

    Reason: keeps the eval focused on the tool-calling surface; semantic
    memory + KG adds variance that swamps cross-model deltas.
    """
    return PydanticAgent(  # ty: ignore[invalid-return-type,no-matching-overload]
        _build_model(provider),
        tools=[
            Tool(query_timeseries),
            Tool(query_markets),
            Tool(list_devices_where),
            Tool(query_energy_breakdown),
        ],
        system_prompt=load_system_prompt(),
    )


async def _run_one(
    agent: PydanticAgent[object],
    case: EvalCase,
    server: EvalServerClient,
) -> CaseResult:
    """Run a single case against one agent, capture metrics.

    `server` is the seeded EvalServerClient — telemetry tools call it
    instead of HTTP since the eval bypasses the FastAPI transport.
    """
    deps = _TelemetryDeps(site_id=EVAL_SITE_ID, server=server)
    t0 = time.perf_counter()
    result = await agent.run(case.prompt, deps=deps)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    usage = result.usage()
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    artifact_kinds = [a.kind for a in deps.artifacts]
    text = str(result.output).lower()

    correctness = 0.0
    if case.expect_keyword in text:
        correctness += 0.5
    if case.expect_artifact is None or case.expect_artifact in artifact_kinds:
        correctness += 0.5

    cost = inp * USD_PER_INPUT_TOK + out * USD_PER_OUTPUT_TOK
    return CaseResult(
        case=case.name,
        latency_ms=elapsed_ms,
        input_tokens=inp,
        output_tokens=out,
        artifact_kinds=artifact_kinds,
        correctness=correctness,
        cost_usd=cost,
    )


async def run_provider(provider: Provider, server: EvalServerClient) -> ProviderReport:
    """Serial pass — never run two cases or two providers concurrently."""
    agent = _build_eval_agent(provider)
    results: list[CaseResult] = [await _run_one(agent, case, server) for case in CASES]
    return ProviderReport(provider=provider, results=results)


async def main() -> None:
    """Entrypoint: spin postgres seed → serial Ollama → Bedrock → write /tmp md."""
    out_dir = Path(os.environ.get("EVAL_OUT_DIR", "/tmp"))  # noqa: S108  # nosec B108
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")

    async with seeded_server_client() as server:
        reports = [
            await run_provider("ollama", server),
            await run_provider("bedrock", server),
        ]

    (out_dir / f"ems-eval-leaderboard-{stamp}.md").write_text(
        render_leaderboard(reports), encoding="utf-8"
    )

    bedrock_avg = (
        reports[1].total_cost_usd / max(len(reports[1].results), 1)
        if reports[1].results
        else 0.0
    )
    (out_dir / f"ems-cost-projection-{stamp}.md").write_text(
        render_cost_projection(bedrock_avg), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
