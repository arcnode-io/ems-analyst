"""Unit tests for the FastAPI server.

Stub the Agent so we test the HTTP layer in isolation — full Agent-loop
integration is in tests/test_integration.py.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi.testclient import TestClient

from .schemas import AnalystMessage
from .server import build_app


@dataclass
class _FakeAgent:
    """Drop-in for Agent — returns a canned AnalystMessage."""

    handler: Callable[[str], Awaitable[AnalystMessage]]

    async def chat_message(self, prompt: str) -> AnalystMessage:
        return await self.handler(prompt)


async def _canned_msg(prompt: str) -> AnalystMessage:
    return AnalystMessage.model_validate(
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": f"You said: {prompt}"},
                {
                    "type": "artifact",
                    "artifact": {
                        "kind": "pie",
                        "spec": {
                            "title": "Test",
                            "unit": "MWh",
                            "slices": [{"label": "solar", "value": 100.0}],
                            "dataAsOf": "2026-05-16T12:00:00Z",
                        },
                    },
                },
            ],
        }
    )


class TestChatEndpoint:
    """AAA for POST /analyst/chat."""

    def test_returns_analyst_message_json(self) -> None:
        # Arrange
        agent = _FakeAgent(handler=_canned_msg)
        client = TestClient(build_app(agent_factory=lambda: agent))

        # Act
        resp = client.post(
            "/analyst/chat",
            json={
                "conversationId": "abc-123",
                "message": "what is the SoC of BESS-01?",
            },
        )

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "assistant"
        assert body["content"][0]["type"] == "text"
        assert "BESS-01" in body["content"][0]["text"]
        assert body["content"][1]["artifact"]["kind"] == "pie"

    def test_rejects_missing_message(self) -> None:
        # Arrange
        client = TestClient(
            build_app(agent_factory=lambda: _FakeAgent(handler=_canned_msg))
        )

        # Act
        resp = client.post(
            "/analyst/chat", json={"conversationId": "x"}
        )

        # Assert — FastAPI 422 on validation failure
        assert resp.status_code == 422

    def test_health_endpoint(self) -> None:
        # Arrange
        client = TestClient(
            build_app(agent_factory=lambda: _FakeAgent(handler=_canned_msg))
        )

        # Act
        resp = client.get("/health")

        # Assert
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
