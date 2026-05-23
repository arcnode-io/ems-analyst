"""Turn execution — drives the pydantic-ai agent and shapes the result.

`run_turn_stream` runs one turn via `agent.iter()`, yielding live tool
events then a terminal `ChatTurnResult`. `lib.Agent` wraps it:
`chat_turn_stream` exposes the generator, `chat_turn` drains it. The
SSE endpoint consumes the generator directly.
"""

import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from pydantic_ai import Agent as PydanticAgent, UsageLimits
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
)

from .device_api import DeviceApiClient
from .memory import MemoryService
from .schemas import AnalystArtifact, AnalystMessage
from .server_client import ServerClient

log = logging.getLogger(__name__)

# Backstop against a tool-call loop — a normal turn is 3-5 calls.
# Hitting it raises UsageLimitExceeded → the turn returns its partials.
_TOOL_CALL_LIMIT: int = 10

# Human-readable action shown in the HMI live-trace per tool call —
# never raw args. Unknown tools fall back to _DEFAULT_TOOL_LABEL.
_TOOL_LABELS: dict[str, str] = {
    "describe_site": "Checking what data is queryable",
    "get_topology": "Reading site topology",
    "query_timeseries": "Querying the site historian",
    "get_forecast": "Pulling the published forecast",
    "query_markets": "Computing market revenue",
    "query_energy_breakdown": "Computing the energy mix",
    "get_weather_forecast": "Checking the weather",
    "get_market_data": "Querying ERCOT market data",
    "get_energy_news": "Scanning energy news",
}
_DEFAULT_TOOL_LABEL: str = "Searching the knowledge base"

# Tools whose result carries a one-line headline worth surfacing in the
# toolTrace `summary` — external-data tools only.
_SUMMARY_TOOLS: frozenset[str] = frozenset(
    {"get_energy_news", "get_market_data", "get_weather_forecast"}
)


class AgentDeps:
    """Dependencies injected into agent tools.

    `artifacts` is the sink telemetry tools append to; the turn assembles
    the final AnalystMessage from prose + this list. `server` is the REST
    client over ems-analyst-server; `device_api` the client over
    ems-device-api (the DTM source of truth).
    """

    def __init__(
        self,
        memory_service: MemoryService,
        server: ServerClient,
        device_api: DeviceApiClient,
    ) -> None:
        self.memory_service = memory_service
        self.server = server
        self.device_api = device_api
        self.artifacts: list[AnalystArtifact] = []


@dataclass
class ChatTurnResult:
    """One agent turn: HMI-facing AnalystMessage + raw pydantic-ai messages.

    `message` is what the HMI renders. `new_messages` is the lossless
    pydantic-ai trace an upstream store persists for replay. `status` is
    the outcome — `ok`, `capped` (tool-call budget hit), or `error`.
    """

    message: AnalystMessage
    new_messages: list[ModelMessage]
    status: str = "ok"


async def run_turn_stream(
    agent: PydanticAgent[AgentDeps],
    deps: AgentDeps,
    prompt: str,
    message_history: list[ModelMessage] | None,
) -> AsyncGenerator[tuple[str, object]]:
    """Run a turn, yielding live tool events then a terminal result.

    Yields, in order:
      ("tool_start", {seq, tool, label})            — per tool call
      ("tool_end",   {seq, tool, outcome, ms, summary})
      ("result", ChatTurnResult)                    — always last

    `seq` pairs a start with its end.
    """
    pending: dict[str, tuple[int, str, float]] = {}
    trace: list[dict[str, object]] = []
    seq = 0
    try:
        async with agent.iter(
            prompt,
            deps=deps,
            message_history=message_history,
            usage_limits=UsageLimits(tool_calls_limit=_TOOL_CALL_LIMIT),
        ) as run:
            async for node in run:
                if not PydanticAgent.is_call_tools_node(node):
                    continue
                async with node.stream(run.ctx) as events:
                    async for event in events:
                        if isinstance(event, FunctionToolCallEvent):
                            seq += 1
                            tool = event.part.tool_name
                            pending[event.part.tool_call_id] = (
                                seq,
                                tool,
                                time.perf_counter(),
                            )
                            yield (
                                "tool_start",
                                {
                                    "seq": seq,
                                    "tool": tool,
                                    "label": _TOOL_LABELS.get(
                                        tool, _DEFAULT_TOOL_LABEL
                                    ),
                                },
                            )
                        elif isinstance(event, FunctionToolResultEvent):
                            started = pending.pop(event.part.tool_call_id, None)
                            if started is None:
                                continue
                            eseq, tool, t0 = started
                            entry = _trace_entry(tool, event, eseq, t0)
                            trace.append(entry)
                            yield "tool_end", entry
            await _store_prompt_memory(deps.memory_service, prompt)
            content: list[dict[str, object]] = [
                {"type": "text", "text": str(run.result.output)},
                *(
                    {"type": "artifact", "artifact": art.model_dump(by_alias=True)}
                    for art in _presentable(deps.artifacts)
                ),
            ]
            message = AnalystMessage.model_validate(
                {
                    "role": "assistant",
                    "content": content,
                    "toolTrace": [_public_trace(t) for t in trace],
                }
            )
            yield (
                "result",
                ChatTurnResult(
                    message=message,
                    new_messages=list(run.result.new_messages()),
                    status="ok",
                ),
            )
    except UsageLimitExceeded:
        # Model looped past the budget — surface partial artifacts.
        log.warning("tool-call limit hit; returning partial artifacts")
        yield "result", _partial_turn(deps.artifacts, trace)


async def _store_prompt_memory(memory_service: MemoryService, prompt: str) -> None:
    """Persist the prompt for semantic recall — best-effort.

    A slow/unreachable embedder must not drop the answer already produced.
    """
    try:
        embedding = await memory_service.generate_embedding(prompt)
        await memory_service.store_memory(f"User stated: {prompt}", embedding)
    except Exception:
        log.warning("memory store skipped — embedder/store down", exc_info=True)


def _presentable(artifacts: list[AnalystArtifact]) -> list[AnalystArtifact]:
    """Trim the raw tool-artifact list to what the user should actually see.

    Two passes: dedupe identical artifacts (a loopy turn repeats tool
    calls), then drop `table` artifacts when a chart is present —
    describe_site / get_topology tables are discovery scaffolding, not
    the answer once a chart was produced.
    """
    seen: set[tuple[str, str]] = set()
    deduped: list[AnalystArtifact] = []
    for art in artifacts:
        key = (art.kind, str(getattr(art.spec, "title", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(art)
    has_chart = any(a.kind in ("line", "bar", "pie") for a in deduped)
    if has_chart:
        return [a for a in deduped if a.kind != "table"]
    return deduped


def _result_summary(tool: str, event: FunctionToolResultEvent) -> str | None:
    """One-line headline from an external tool's result; None otherwise.

    Only the external-data tools carry something headline-shaped — the
    HMI intel feed surfaces it. First non-empty line, trimmed.
    """
    if tool not in _SUMMARY_TOOLS:
        return None
    text = str(getattr(event.part, "content", "")).strip()
    if not text:
        return None
    return text.splitlines()[0].strip()[:140] or None


def _trace_entry(
    tool: str, event: FunctionToolResultEvent, seq: int, t0: float
) -> dict[str, object]:
    """Build a trace row from a completed tool call (carries stream `seq`)."""
    outcome = "ok" if getattr(event.part, "part_kind", "") == "tool-return" else "error"
    return {
        "seq": seq,
        "tool": tool,
        "label": _TOOL_LABELS.get(tool, _DEFAULT_TOOL_LABEL),
        "outcome": outcome,
        "ms": int((time.perf_counter() - t0) * 1000),
        "summary": _result_summary(tool, event),
    }


def _public_trace(entry: dict[str, object]) -> dict[str, object]:
    """toolTrace row for the AnalystMessage — drops the stream-only `seq`."""
    return {k: v for k, v in entry.items() if k != "seq"}


def _partial_turn(
    artifacts: list[AnalystArtifact], trace: list[dict[str, object]]
) -> ChatTurnResult:
    """Assemble a turn from artifacts gathered before the tool-call cap.

    The model looped past its budget. Whatever charts it built are still
    useful — keep the presentable set, drop error artifacts, surface the
    rest with a brief note instead of a bare failure.
    """
    kept = [a for a in _presentable(artifacts) if a.kind != "error"]
    note = (
        "I ran long working through that — here's the data I gathered. "
        "Ask a follow-up if you need more."
        if kept
        else "I couldn't finish that one — I ran out of tool budget before "
        "reaching an answer. Try a narrower question."
    )
    content: list[dict[str, object]] = [
        {"type": "text", "text": note},
        *(
            {"type": "artifact", "artifact": art.model_dump(by_alias=True)}
            for art in kept
        ),
    ]
    return ChatTurnResult(
        message=AnalystMessage.model_validate(
            {
                "role": "assistant",
                "content": content,
                "toolTrace": [_public_trace(t) for t in trace],
            }
        ),
        new_messages=[],
        status="capped",
    )
