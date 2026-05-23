"""Adversarial scoring helpers for the with-MCP eval.

Separated from eval_mcp.py so the line-budget for the runner stays sane.
Pure functions over pydantic-ai message history — unit-testable without
spinning up the agent.
"""

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)

# Local tool names — anything else came from the MCP server.
LOCAL_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_weather_forecast",
        "get_market_data",
        "get_energy_news",
        "query_timeseries",
        "query_markets",
        "query_energy_breakdown",
    }
)


def count_mcp_calls(messages: list[ModelResponse]) -> int:
    """Tool calls aimed at MCP (LLM-side attempts, not return success)."""
    return sum(
        1
        for msg in messages
        for part in msg.parts
        if isinstance(part, ToolCallPart) and part.tool_name not in LOCAL_TOOL_NAMES
    )


def count_mcp_successes(all_messages: list[ModelMessage]) -> int:
    """MCP tool returns that delivered content (outcome=success + non-empty).

    Reason: counting call *attempts* was the lazy v1 metric — scored 100%
    even when graphiti errored internally. Reality only shows up in the
    ToolReturnPart that follows the ToolCallPart.
    """
    n = 0
    for msg in all_messages:
        if not isinstance(msg, ModelRequest):
            continue
        for part in msg.parts:
            if not isinstance(part, ToolReturnPart):
                continue
            if part.tool_name in LOCAL_TOOL_NAMES:
                continue
            outcome = getattr(part, "outcome", "success")
            content_str = str(part.content) if part.content is not None else ""
            if outcome == "success" and content_str.strip() and content_str != "[]":
                n += 1
    return n


def score_case(*, mcp_ok: int, keyword_in_text: bool) -> float:
    """Stricter rubric — penalize training-data leak through.

    - 1.00: MCP returned non-empty content AND keyword in answer
    - 0.50: only one of the two conditions met (and not the leak case)
    - 0.25: keyword present without MCP grounding (training-data leak)
    - 0.00: both missed
    """
    if mcp_ok == 0 and keyword_in_text:
        return 0.25
    score = 0.0
    if mcp_ok > 0:
        score += 0.5
    if keyword_in_text:
        score += 0.5
    return score
