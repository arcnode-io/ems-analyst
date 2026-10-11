"""Turn execution — drives the pydantic-ai agent loop.

`run_turn_stream` runs one turn via `agent.iter()`, yielding live tool
events then a terminal `ChatTurnResult`. `lib.Agent` wraps it:
`chat_turn_stream` exposes the generator, `chat_turn` drains it. The
SSE endpoint consumes the generator directly.

Result-shaping (what a turn's final message/artifacts look like, for
both the normal and early-ending paths) lives in turn_results.py — this
module is just the live loop + the scope-filter pre-gate.
"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import Final

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
from .scope_filter import ScopeFilter
from .server_client import ServerClient
from .turn_results import (
    ChatTurnResult,
    degraded_turn,
    out_of_scope_result,
    presentable,
    public_trace,
)
from .turn_trace import DEFAULT_TOOL_LABEL, TOOL_LABELS, trace_entry

log = logging.getLogger(__name__)

# Backstop against a tool-call loop — a normal turn is 3-5 calls.
# Hitting it raises UsageLimitExceeded → the turn returns its partials.
_TOOL_CALL_LIMIT: int = 10

# Backstop against the whole turn hanging (slow local-model generation,
# e.g. a dual-GPU-split 26B model taking minutes on a long answer) — the
# user otherwise sees nothing at all until they give up. 90s comfortably
# covers every normal turn observed (3-50s) with margin.
_TURN_TIMEOUT_SEC: Final[float] = 90.0


class AgentDeps:
    """Dependencies injected into agent tools.

    `artifacts` is the sink telemetry tools append to; the turn assembles
    the final AnalystMessage from prose + this list. `server` is the REST
    client over ems-analyst-server; `device_api` the client over
    ems-device-api (the DTM source of truth). `site_description_cache` /
    `topology_cache` / `focused_device_id` mirror `_TelemetryDeps` — see
    its docstring. Constructed fresh per turn, so nothing here persists
    across turns.
    """

    def __init__(
        self,
        memory_service: MemoryService,
        server: ServerClient,
        device_api: DeviceApiClient,
        focused_device_id: str | None = None,
    ) -> None:
        self.memory_service = memory_service
        self.server = server
        self.device_api = device_api
        self.focused_device_id = focused_device_id
        self.artifacts: list[AnalystArtifact] = []
        self.site_description_cache: AnalystArtifact | None = None
        self.topology_cache: AnalystArtifact | None = None


# Module-level singleton — anchors are embedded once on first in_scope
# call and cached for the process lifetime. Lazy-init so test code that
# doesn't exercise the gate doesn't trigger the 20-anchor embed batch.
_scope_filter: ScopeFilter | None = None


def _get_scope_filter(deps: AgentDeps) -> ScopeFilter:
    """Return the process-wide scope filter, constructing it on first use."""
    global _scope_filter  # noqa: PLW0603  # intentional lazy module singleton
    if _scope_filter is None:
        _scope_filter = ScopeFilter(deps.memory_service.embedder)
    return _scope_filter


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
    if not await _get_scope_filter(deps).in_scope(prompt):
        log.info("scope filter rejected query (no LLM call)")
        yield "result", out_of_scope_result()
        return
    pending: dict[str, tuple[int, str, float]] = {}
    trace: list[dict[str, object]] = []
    seq = 0
    try:
        async with (
            asyncio.timeout(_TURN_TIMEOUT_SEC),
            agent.iter(
                prompt,
                deps=deps,
                message_history=message_history,
                usage_limits=UsageLimits(tool_calls_limit=_TOOL_CALL_LIMIT),
            ) as run,
        ):
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
                                    "label": TOOL_LABELS.get(tool, DEFAULT_TOOL_LABEL),
                                },
                            )
                        elif isinstance(event, FunctionToolResultEvent):
                            started = pending.pop(event.part.tool_call_id, None)
                            if started is None:
                                continue
                            eseq, tool, t0 = started
                            entry = trace_entry(tool, event, eseq, t0)
                            trace.append(entry)
                            yield "tool_end", entry
            content: list[dict[str, object]] = [
                {"type": "text", "text": str(run.result.output)},
                *(
                    {"type": "artifact", "artifact": art.model_dump(by_alias=True)}
                    for art in presentable(deps.artifacts)
                ),
            ]
            message = AnalystMessage.model_validate(
                {
                    "role": "assistant",
                    "content": content,
                    "toolTrace": [public_trace(t) for t in trace],
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
        yield (
            "result",
            degraded_turn(
                deps.artifacts,
                trace,
                status="capped",
                note_with_data="I ran long working through that — here's the data "
                "I gathered. Ask a follow-up if you need more.",
                note_without_data="I couldn't finish that one — I ran out of tool "
                "budget before reaching an answer. Try a narrower question.",
            ),
        )
    except TimeoutError:
        # Turn outran the wall-clock bound (e.g. slow local-model
        # generation) — the caller otherwise waits forever for nothing.
        log.warning(
            "turn exceeded %.0fs; returning partial artifacts", _TURN_TIMEOUT_SEC
        )
        yield (
            "result",
            degraded_turn(
                deps.artifacts,
                trace,
                status="timeout",
                note_with_data="That took too long to finish — here's the data "
                "I gathered. Ask a follow-up if you need more.",
                note_without_data="That took too long to answer. Try a narrower "
                "question, or try again in a moment.",
            ),
        )
