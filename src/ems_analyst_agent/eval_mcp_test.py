"""Unit tests for eval_mcp helpers — pure logic only.

The full MCP run lives behind `poe eval-mcp` (testcontainers + live LLM).
Here we just verify the tool-call counter routes correctly.
"""

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

from .eval_mcp import _LOCAL_TOOL_NAMES, _count_mcp_calls


def _msg(tool_names: list[str]) -> ModelResponse:
    parts: list[TextPart | ToolCallPart] = [
        ToolCallPart(tool_name=name, args={}, tool_call_id=str(i))
        for i, name in enumerate(tool_names)
    ]
    return ModelResponse(parts=parts)


class TestCountMcpCalls:
    def test_local_tools_not_counted(self) -> None:
        # Arrange
        msgs = [_msg(list(_LOCAL_TOOL_NAMES))]

        # Act
        n = _count_mcp_calls(msgs)

        # Assert
        assert n == 0

    def test_unknown_tools_counted_as_mcp(self) -> None:
        # Arrange
        msgs = [_msg(["combined_search", "rag_search"])]

        # Act
        n = _count_mcp_calls(msgs)

        # Assert
        assert n == 2

    def test_mixed_counted_correctly(self) -> None:
        # Arrange
        msgs = [
            _msg(["query_timeseries", "combined_search"]),
            _msg(["verify_fact"]),
        ]

        # Act
        n = _count_mcp_calls(msgs)

        # Assert
        assert n == 2

    def test_text_parts_ignored(self) -> None:
        # Arrange
        msg = ModelResponse(parts=[TextPart(content="just text")])

        # Act
        n = _count_mcp_calls([msg])

        # Assert
        assert n == 0
