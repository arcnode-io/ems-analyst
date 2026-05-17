"""With-MCP eval — adds the domain MCP server to the eval agent.

Spawns Neo4j + pgvector testcontainers, sets GRAPH_URL + VECTOR_URL,
wires the MCP toolset into the eval agent so the LLM can call
`combined_search`, `rag_search`, `verify_fact`, etc.

The corpus is NOT seeded in this v1 — the test mirrors the existing
integration fixture path which also runs MCP corpus-empty. The signal
we're after is *whether the model invokes MCP tools when asked
domain-grounded questions* — not whether the corpus returns the right
answer.

Run via `poe eval-mcp` — writes `/tmp/ems-eval-mcp-leaderboard-YYYY-MM-DD.md`.

See [[project-eval-limitations]] for the v1.2 plan: seed the real
corpus and measure answer quality delta with-vs-without MCP.
"""

import asyncio
import os
import sys
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import pook
from pydantic_ai import Agent as PydanticAgent, Tool
from pydantic_ai.messages import ModelResponse, ToolCallPart

from .eval import EvalCase, _build_model
from .eval_report import (
    USD_PER_INPUT_TOK,
    USD_PER_OUTPUT_TOK,
    CaseResult,
    McpCaseResult,
    Provider,
    ProviderReport,
    render_mcp_leaderboard,
)
from .prompts import load_system_prompt
from .tools.domain_mcp import create_mcp_server
from .tools.telemetry import (
    _ArtifactSink,
    list_devices_where,
    query_energy_breakdown,
    query_markets,
    query_timeseries,
)

# Re-use the testcontainer helpers from the integration test layer.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
from tests.fixtures.containers import start_neo4j, start_postgres  # noqa: E402

NEO4J_PASSWORD: str = "evalpw"  # noqa: S105 — testcontainer only

# Known non-MCP tool names — anything else came from the MCP server.
_LOCAL_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_weather_forecast",
        "get_market_data",
        "get_energy_news",
        "query_timeseries",
        "query_markets",
        "list_devices_where",
        "query_energy_breakdown",
    }
)


# ── corpus-grounded cases (need MCP to answer well) ───────────────────────

MCP_CASES: list[EvalCase] = [
    EvalCase(
        name="modbus_function_code_3",
        prompt=(
            "Per the Modbus application protocol spec, what is function "
            "code 3 used for? Search the knowledge base."
        ),
        expect_artifact=None,
        expect_keyword="holding",
    ),
    EvalCase(
        name="hollifield_hmi_palette",
        prompt=(
            "According to Hollifield's HMI design guide, what's the "
            "recommended baseline palette for normal operations? "
            "Use the knowledge base."
        ),
        expect_artifact=None,
        expect_keyword="gray",
    ),
    EvalCase(
        name="bess_thermal",
        prompt=(
            "What does the BESS book say about thermal runaway "
            "containment strategies? Search the knowledge base."
        ),
        expect_artifact=None,
        expect_keyword="thermal",
    ),
]


def _count_mcp_calls(messages: list[ModelResponse]) -> int:
    """Inspect agent message history for tool calls outside the local set."""
    n = 0
    for msg in messages:
        for part in msg.parts:
            if (
                isinstance(part, ToolCallPart)
                and part.tool_name not in _LOCAL_TOOL_NAMES
            ):
                n += 1
    return n


async def _run_one_with_mcp(
    agent: PydanticAgent[object], case: EvalCase
) -> McpCaseResult:
    deps = _ArtifactSink()
    t0 = time.perf_counter()
    result = await agent.run(case.prompt, deps=deps)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    usage = result.usage()
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    text = str(result.output).lower()
    artifact_kinds = [a.kind for a in deps.artifacts]
    msgs = [m for m in result.all_messages() if isinstance(m, ModelResponse)]
    mcp_n = _count_mcp_calls(msgs)

    correctness = 0.0
    if case.expect_keyword in text:
        correctness += 0.5
    if mcp_n > 0:  # rewarding tool use is the whole point of MCP-mode
        correctness += 0.5

    cost = inp * USD_PER_INPUT_TOK + out * USD_PER_OUTPUT_TOK
    return McpCaseResult(
        case=case.name,
        latency_ms=elapsed_ms,
        input_tokens=inp,
        output_tokens=out,
        artifact_kinds=artifact_kinds,
        correctness=correctness,
        cost_usd=cost,
        mcp_calls=mcp_n,
    )


async def run_with_mcp(provider: Provider) -> ProviderReport:
    """Run MCP_CASES against MCP-enabled agent, serial.

    Backend selection:
    - If GRAPH_URL + VECTOR_URL already set in env → use them (real
      seeded corpus path).
    - Else → spawn ephemeral Neo4j + pgvector testcontainers (empty
      corpus — only measures tool invocation, not answer quality).

    Caller is responsible for serialisation across providers — never call
    this twice in parallel (Ollama melts).
    """
    use_existing = bool(os.environ.get("GRAPH_URL")) and bool(
        os.environ.get("VECTOR_URL")
    )
    with ExitStack() as stack:
        if not use_existing:
            neo4j = stack.enter_context(start_neo4j(NEO4J_PASSWORD))
            pg = stack.enter_context(
                start_postgres(password=os.environ["POSTGRES_PASSWORD"])
            )
            parsed = urlparse(neo4j.url)
            os.environ["GRAPH_URL"] = (
                f"{parsed.scheme}://neo4j:{NEO4J_PASSWORD}@{parsed.netloc}"
            )
            os.environ["VECTOR_URL"] = pg.url

        mcp_server = create_mcp_server()
        agent = PydanticAgent(
            _build_model(provider),
            tools=[
                Tool(query_timeseries),
                Tool(query_markets),
                Tool(list_devices_where),
                Tool(query_energy_breakdown),
            ],
            toolsets=[mcp_server],
            system_prompt=load_system_prompt(),
        )
        results: list[CaseResult] = [
            await _run_one_with_mcp(agent, case) for case in MCP_CASES
        ]
    return ProviderReport(provider=provider, results=results)


async def main() -> None:
    """Serial Ollama → Bedrock with-MCP runs. Writes /tmp leaderboard."""
    pook.off()  # in case something else turned it on this process
    out_dir = Path(os.environ.get("EVAL_OUT_DIR", "/tmp"))  # noqa: S108  # nosec B108
    out_dir.mkdir(parents=True, exist_ok=True)
    reports = [await run_with_mcp("ollama"), await run_with_mcp("bedrock")]
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    (out_dir / f"ems-eval-mcp-leaderboard-{stamp}.md").write_text(
        render_mcp_leaderboard(reports), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
