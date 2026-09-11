"""HTTP route test for POST /analyst/chat.

Exercises the real ConversationController wiring — classy_fastapi's
Routable + the module-level `_check_chat_rate_limit` slowapi gate —
through TestClient's real ASGI stack. A fake service stands in for
ConversationService so no Postgres/agent/Ollama is needed.

This is the coverage gap that let a slowapi/classy_fastapi binding bug
(IndexError in slowapi's arg lookup, since Routable binds routes as
functools.partial(method, self)) reach production undetected: every
other test either called ConversationService directly (bypassing the
route+decorator layer) or only hit OPTIONS preflight, never a real POST.
"""

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.conversations.conversation_controller import ConversationController
from src.conversations.conversation_service import ConversationService
from src.conversations.dto import AnalystChatRequest
from src.rate_limit import limiter
from ems_analyst_agent.schemas import AnalystMessage


class _FakeConversationService:
    """Returns a canned AnalystMessage; records calls."""

    def __init__(self) -> None:
        self.calls: list[AnalystChatRequest] = []

    async def handle_turn(self, req: AnalystChatRequest) -> AnalystMessage:
        self.calls.append(req)
        return AnalystMessage.model_validate(
            {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}
        )


@pytest.fixture
def client() -> tuple[TestClient, _FakeConversationService]:
    limiter.reset()
    fake = _FakeConversationService()
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(ConversationController(cast(ConversationService, fake)).router)
    return TestClient(app), fake


class TestConversationRoute:
    """AAA — POST /analyst/chat reaches the service through the real route."""

    def test_chat_returns_assistant_message(
        self, client: tuple[TestClient, _FakeConversationService]
    ) -> None:
        # Arrange
        c, fake = client

        # Act
        response = c.post(
            "/analyst/chat",
            json={"conversationId": "conv-1", "message": "what's up"},
        )

        # Assert
        assert response.status_code == 200
        assert response.json()["role"] == "assistant"
        assert fake.calls[0].message == "what's up"

    def test_chat_rate_limit_returns_429_past_threshold(
        self, client: tuple[TestClient, _FakeConversationService]
    ) -> None:
        # Arrange — _CHAT_RATE_LIMIT is 20/minute; drive it past the cap
        c, _ = client
        body = {"conversationId": "conv-2", "message": "hi"}

        # Act
        responses = [c.post("/analyst/chat", json=body) for _ in range(21)]

        # Assert
        assert [r.status_code for r in responses[:20]] == [200] * 20
        assert responses[20].status_code == 429
