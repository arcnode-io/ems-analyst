"""Unit tests for run_turn_stream — the live pydantic-ai loop itself.

Pure-function helpers it calls into (presentable, degraded_turn, trace
labeling) are tested where they live: turn_results_test.py, turn_trace
has no non-trivial branches of its own to test.
"""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from .device_api import DeviceApiClient
from .memory import MemoryService
from .schemas import TextContent
from .server_client import ServerClient
from .turn import AgentDeps, run_turn_stream
from .turn_results import ChatTurnResult


async def _drain(
    gen: AsyncGenerator[tuple[str, object]],
) -> ChatTurnResult:
    """Fully drain run_turn_stream the way lib.Agent.chat_turn does."""
    result: ChatTurnResult | None = None
    async for name, payload in gen:
        if name == "result":
            assert isinstance(payload, ChatTurnResult)
            result = payload
    assert result is not None
    return result


def _deps() -> AgentDeps:
    return AgentDeps(
        memory_service=Mock(spec=MemoryService),
        server=Mock(spec=ServerClient),
        device_api=Mock(spec=DeviceApiClient),
    )


class TestRunTurnStreamTimeout:
    """AAA — a turn that outruns the wall-clock bound returns, doesn't hang."""

    @pytest.mark.asyncio
    async def test_slow_model_call_times_out_with_a_graceful_result(self) -> None:
        # Arrange — model never responds inside the (patched, tiny) deadline
        async def _never_responds(
            _messages: list[ModelMessage], _info: AgentInfo
        ) -> ModelResponse:
            await asyncio.sleep(10)
            return ModelResponse(parts=[TextPart(content="too late")])

        agent: PydanticAgent[AgentDeps] = PydanticAgent(
            FunctionModel(_never_responds), deps_type=AgentDeps
        )
        fake_scope_filter = Mock()
        fake_scope_filter.in_scope = AsyncMock(return_value=True)

        # Act
        with (
            patch(
                "ems_analyst_agent.turn._get_scope_filter",
                return_value=fake_scope_filter,
            ),
            patch("ems_analyst_agent.turn._TURN_TIMEOUT_SEC", 0.05),
        ):
            result = await _drain(
                run_turn_stream(agent, _deps(), "how's the weather", None)
            )

        # Assert — a clean result comes back, the hang never reaches the caller
        assert result.status == "timeout"
        first = result.message.content[0]
        assert isinstance(first, TextContent)
        assert "took too long" in first.text.lower()
