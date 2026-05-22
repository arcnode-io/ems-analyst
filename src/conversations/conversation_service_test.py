"""Unit tests for ConversationService — fake store + fake agent.

Full HTTP + testcontainer integration lives in tests/test_conversations.py.
"""

import pytest
from ems_analyst_agent.lib import ChatTurnResult
from ems_analyst_agent.schemas import AnalystMessage

from .conversation_service import ConversationService
from .conversation_store import SiteIdMismatchError
from .dto import AnalystChatRequest, ChatContext


class _FakeStore:
    """In-memory ConversationStore stand-in."""

    def __init__(self) -> None:
        self.site_ids: dict[str, str] = {}
        self.histories: dict[str, list[object]] = {}
        self.appended: dict[str, list[object]] = {}

    async def get_site_id(self, cid: str) -> str | None:
        return self.site_ids.get(cid)

    async def create(self, cid: str, site_id: str) -> None:
        self.site_ids[cid] = site_id

    async def load_history(self, cid: str) -> list[object]:
        return list(self.histories.get(cid, []))

    async def append_messages(self, cid: str, msgs: list[object]) -> None:
        self.appended.setdefault(cid, []).extend(msgs)


class _FakeAgent:
    """ems_analyst_agent.Agent stand-in returning a canned turn."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []

    def _turn(self, prompt: str) -> ChatTurnResult:
        return ChatTurnResult(
            message=AnalystMessage.model_validate(
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": f"echo: {prompt}"}],
                }
            ),
            new_messages=[],  # type: ignore[list-item] — unit-test stub
        )

    async def chat_turn(
        self, prompt: str, *, message_history: list[object] | None = None
    ) -> ChatTurnResult:
        self.calls.append((prompt, list(message_history or [])))
        return self._turn(prompt)

    async def chat_turn_stream(
        self, prompt: str, *, message_history: list[object] | None = None
    ) -> object:
        """Async-gen stand-in — a tool_start/tool_end pair then the result."""
        self.calls.append((prompt, list(message_history or [])))
        yield "tool_start", {"seq": 1, "tool": "describe_site", "label": "L"}
        yield (
            "tool_end",
            {"seq": 1, "tool": "describe_site", "outcome": "ok", "ms": 5},
        )
        yield "result", self._turn(prompt)


def _service_with_fakes() -> tuple[ConversationService, _FakeStore, _FakeAgent]:
    svc = ConversationService()
    fake_store = _FakeStore()
    fake_agent = _FakeAgent()
    svc._store = fake_store  # ty: ignore[invalid-assignment]
    svc._agent = fake_agent  # ty: ignore[invalid-assignment]
    return svc, fake_store, fake_agent


class TestHandleTurn:
    """AAA per branch — first turn, replay, siteId mismatch."""

    @pytest.mark.asyncio
    async def test_first_turn_creates_conversation(self) -> None:
        # Arrange
        svc, store, agent = _service_with_fakes()
        svc._baked_site_id = "site-a"  # match request
        req = AnalystChatRequest(
            conversation_id="11111111-1111-1111-1111-111111111111",
            message="hi",
            context=ChatContext(site_id="site-a"),
        )

        # Act
        msg = await svc.handle_turn(req)

        # Assert
        assert store.site_ids[req.conversation_id] == "site-a"
        assert agent.calls[0] == ("hi", [])
        assert "echo: hi" in str(msg.model_dump_json())

    @pytest.mark.asyncio
    async def test_subsequent_turn_loads_history(self) -> None:
        # Arrange
        svc, store, agent = _service_with_fakes()
        svc._baked_site_id = "site-b"  # match request
        cid = "22222222-2222-2222-2222-222222222222"
        store.site_ids[cid] = "site-b"
        store.histories[cid] = ["sentinel1", "sentinel2"]
        req = AnalystChatRequest(
            conversation_id=cid,
            message="follow-up",
            context=ChatContext(site_id="site-b"),
        )

        # Act
        await svc.handle_turn(req)

        # Assert — agent saw history pre-loaded
        assert agent.calls[0] == ("follow-up", ["sentinel1", "sentinel2"])

    @pytest.mark.asyncio
    async def test_site_id_mismatch_raises(self) -> None:
        # Arrange
        svc, store, _ = _service_with_fakes()
        cid = "33333333-3333-3333-3333-333333333333"
        store.site_ids[cid] = "site-a"
        req = AnalystChatRequest(
            conversation_id=cid,
            message="x",
            context=ChatContext(site_id="site-b"),
        )

        # Act + Assert
        with pytest.raises(SiteIdMismatchError):
            await svc.handle_turn(req)

    @pytest.mark.asyncio
    async def test_request_site_mismatches_deployment_site(self) -> None:
        # Arrange — baked deployment is 'site-prod', client sends 'site-other'
        svc, _, _ = _service_with_fakes()
        svc._baked_site_id = "site-prod"  # bypass cfg lookup
        req = AnalystChatRequest(
            conversation_id="44444444-4444-4444-4444-444444444444",
            message="x",
            context=ChatContext(site_id="site-other"),
        )

        # Act + Assert
        with pytest.raises(SiteIdMismatchError, match="this deployment"):
            await svc.handle_turn(req)


class _CrashingStore:
    """Duck-typed store whose first call fails like an unreachable Postgres."""

    async def get_site_id(self, _cid: str) -> str | None:
        raise OSError("Postgres unreachable")


class TestHandleTurnErrorBoundary:
    """A turn must never surface as HTTP 500 — HMI brief contract."""

    @pytest.mark.asyncio
    async def test_store_failure_returns_error_artifact(self) -> None:
        # Arrange — store blows up the way an unreachable Postgres would
        svc, _, _ = _service_with_fakes()
        svc._store = _CrashingStore()  # ty: ignore[invalid-assignment]
        svc._baked_site_id = "site-a"  # match request → past the 409 check
        req = AnalystChatRequest(
            conversation_id="55555555-5555-5555-5555-555555555555",
            message="hello",
            context=ChatContext(site_id="site-a"),
        )

        # Act — must not raise; the store error is outside the old try
        msg = await svc.handle_turn(req)

        # Assert — degraded to a 200 error-artifact, not a 500
        assert msg.role == "assistant"
        assert '"kind":"error"' in msg.model_dump_json()


class TestStreamTurn:
    """stream_turn emits SSE frames — tool events then a terminal message."""

    @pytest.mark.asyncio
    async def test_emits_tool_events_then_message_and_done(self) -> None:
        # Arrange
        svc, _, _ = _service_with_fakes()
        svc._baked_site_id = "site-a"
        req = AnalystChatRequest(
            conversation_id="66666666-6666-6666-6666-666666666666",
            message="hi",
            context=ChatContext(site_id="site-a"),
        )

        # Act — caller supplies history (controller ran ensure_conversation)
        blob = b"".join([f async for f in svc.stream_turn(req, [])]).decode()

        # Assert — every contract event, in SSE frame form, terminal done
        assert "event: tool_start" in blob
        assert "event: tool_end" in blob
        assert "event: message" in blob
        assert 'event: done\ndata: {"status": "ok"}' in blob
