"""Shaping a ChatTurnResult from whatever a turn gathered.

Pure functions — no agent, no streaming, no network. `turn.py`'s
`run_turn_stream` drives the live pydantic-ai loop and calls into this
module to build what it ultimately yields as the terminal result.
"""

from dataclasses import dataclass

from pydantic_ai.messages import ModelMessage

from .schemas import AnalystArtifact, AnalystMessage


@dataclass
class ChatTurnResult:
    """One agent turn: HMI-facing AnalystMessage + raw pydantic-ai messages.

    `message` is what the HMI renders. `new_messages` is the lossless
    pydantic-ai trace an upstream store persists for replay. `status` is
    the outcome — `ok`, `capped` (tool-call budget hit), `timeout` (wall-
    clock bound hit), `out_of_scope`, or `error`.
    """

    message: AnalystMessage
    new_messages: list[ModelMessage]
    status: str = "ok"


_OUT_OF_SCOPE_TEXT: str = (
    "I'm scoped to grid, markets, BESS, protocols, and weather/demand "
    "topics — that question's outside my domain."
)


def out_of_scope_result() -> ChatTurnResult:
    """Synthetic terminal result for queries the pre-gate rejected."""
    message = AnalystMessage.model_validate(
        {
            "role": "assistant",
            "content": [{"type": "text", "text": _OUT_OF_SCOPE_TEXT}],
            "toolTrace": [],
        }
    )
    return ChatTurnResult(message=message, new_messages=[], status="out_of_scope")


def presentable(artifacts: list[AnalystArtifact]) -> list[AnalystArtifact]:
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


def public_trace(entry: dict[str, object]) -> dict[str, object]:
    """toolTrace row for the AnalystMessage — drops the stream-only `seq`."""
    return {k: v for k, v in entry.items() if k != "seq"}


def degraded_turn(
    artifacts: list[AnalystArtifact],
    trace: list[dict[str, object]],
    *,
    status: str,
    note_with_data: str,
    note_without_data: str,
) -> ChatTurnResult:
    """Assemble a turn that ended early — tool-budget cap or wall-clock timeout.

    Either way, whatever charts the model built so far are still useful —
    keep the presentable set, drop error artifacts, surface the rest with
    a brief note instead of a bare failure.
    """
    kept = [a for a in presentable(artifacts) if a.kind != "error"]
    content: list[dict[str, object]] = [
        {"type": "text", "text": note_with_data if kept else note_without_data},
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
                "toolTrace": [public_trace(t) for t in trace],
            }
        ),
        new_messages=[],
        status=status,
    )
