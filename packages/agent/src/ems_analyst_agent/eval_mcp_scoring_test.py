"""Unit tests for the adversarial scoring helpers."""

from typing import Literal, cast

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)

from .eval_mcp_scoring import (
    LOCAL_TOOL_NAMES,
    count_mcp_calls,
    count_mcp_successes,
    score_case,
)


def _call_msg(names: list[str]) -> ModelResponse:
    parts = [
        ToolCallPart(tool_name=n, args={}, tool_call_id=str(i))
        for i, n in enumerate(names)
    ]
    return ModelResponse(parts=parts)


def _return_msg(
    name: str,
    content: object,
    outcome: Literal["success", "failed", "denied"] = "success",
) -> list[ModelMessage]:
    part = ToolReturnPart(
        tool_name=name, content=cast("str", content), tool_call_id="x"
    )
    part.outcome = outcome
    return [ModelRequest(parts=[part])]


class TestCountMcpCalls:
    def test_local_tool_skipped(self) -> None:
        assert count_mcp_calls([_call_msg(list(LOCAL_TOOL_NAMES))]) == 0

    def test_mcp_tool_counted(self) -> None:
        assert count_mcp_calls([_call_msg(["combined_search", "rag_search"])]) == 2

    def test_text_parts_ignored(self) -> None:
        assert count_mcp_calls([ModelResponse(parts=[TextPart(content="hi")])]) == 0


class TestCountMcpSuccesses:
    def test_successful_non_empty_return_counted(self) -> None:
        msgs = _return_msg("combined_search", "found 3 results", "success")
        assert count_mcp_successes(msgs) == 1

    def test_failed_outcome_skipped(self) -> None:
        msgs = _return_msg("combined_search", "boom", "failed")
        assert count_mcp_successes(msgs) == 0

    def test_empty_content_skipped(self) -> None:
        msgs = _return_msg("combined_search", "", "success")
        assert count_mcp_successes(msgs) == 0

    def test_empty_list_content_skipped(self) -> None:
        msgs = _return_msg("combined_search", "[]", "success")
        assert count_mcp_successes(msgs) == 0

    def test_local_tool_skipped(self) -> None:
        msgs = _return_msg("query_timeseries", "data", "success")
        assert count_mcp_successes(msgs) == 0


class TestScoreCase:
    def test_full_credit_both_conditions(self) -> None:
        assert score_case(mcp_ok=2, keyword_in_text=True) == 1.0

    def test_mcp_only_half_credit(self) -> None:
        assert score_case(mcp_ok=1, keyword_in_text=False) == 0.5

    def test_keyword_without_mcp_is_training_leak_penalty(self) -> None:
        assert score_case(mcp_ok=0, keyword_in_text=True) == 0.25

    def test_neither_zero(self) -> None:
        assert score_case(mcp_ok=0, keyword_in_text=False) == 0.0
