"""Orchestrates conversation store + ems_analyst_agent.Agent for one turn.

Two surfaces over the same turn: `handle_turn` returns the final
AnalystMessage (JSON callers); `stream_turn` yields SSE frames —
live tool-trace events then a terminal message+done — for the HMI's
live-trace UI. The controller content-negotiates on `Accept`.
"""

import json
import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from ems_analyst_agent.lib import Agent, ChatTurnResult
from ems_analyst_agent.schemas import AnalystMessage
from pydantic_ai.messages import ModelMessage

from .conversation_store import ConversationStore, SiteIdMismatchError
from .dto import AnalystChatRequest

log = logging.getLogger(__name__)

_VECTOR_URL_ENV: str = "VECTOR_URL"


def _sse(event: str, data: object) -> bytes:
    """Encode one SSE frame — `event:`/`data:` lines, blank-line terminated."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


class ConversationService:
    """One agent turn end-to-end with thread persistence + siteId enforcement."""

    def __init__(self) -> None:
        """Lazy singletons — first request spawns the agent + checks the DB."""
        self._agent: Agent | None = None
        self._store: ConversationStore | None = None
        self._baked_site_id: str | None = None

    def _agent_instance(self) -> Agent:
        if self._agent is None:
            self._agent = Agent()
        return self._agent

    def _store_instance(self) -> ConversationStore:
        if self._store is None:
            self._store = ConversationStore(postgres_url=os.environ[_VECTOR_URL_ENV])
        return self._store

    def _site_id(self) -> str:
        """Per-deployment site_id baked into ems-analyst-agent's cfg.

        Lazy — load_config() is cheap (one YAML read + pydantic) so we cache
        for the lifetime of the service.
        """
        if self._baked_site_id is None:
            from ems_analyst_agent.config import load_config

            self._baked_site_id = load_config().site_id
        return self._baked_site_id

    async def ensure_conversation(self, req: AnalystChatRequest) -> list[ModelMessage]:
        """Validate siteId, create the row on first turn, return thread history.

        Validates request.context.siteId in two layers:
        1. Against the server's baked SITE_ID (per-deployment) → 409.
        2. Against the first-turn siteId stored on the conversation → 409.

        Run before streaming so a mismatch can still surface as HTTP 409
        (a StreamingResponse has already committed 200 once it opens).

        Raises:
            SiteIdMismatchError: on either layer's mismatch (→ HTTP 409).
        """
        store = self._store_instance()
        request_site = req.context.site_id if req.context else None
        baked_site = self._site_id()
        if request_site is not None and baked_site and request_site != baked_site:
            raise SiteIdMismatchError(
                f"siteId {request_site!r} does not match this deployment "
                f"({baked_site!r})"
            )
        stored_site = await store.get_site_id(req.conversation_id)
        if stored_site is None:
            await store.create(req.conversation_id, request_site or baked_site or "")
        elif request_site is not None and request_site != stored_site:
            raise SiteIdMismatchError(
                f"siteId {request_site!r} != stored {stored_site!r}"
            )
        return await store.load_history(req.conversation_id)

    async def handle_turn(self, req: AnalystChatRequest) -> AnalystMessage:
        """Run one turn, return the final AnalystMessage (JSON callers).

        Any infra failure (Postgres unreachable, MCP child crash, Ollama
        timeout, Bedrock 503) degrades to a 200 error-artifact per the
        HMI brief; never an HTTP 500. Only SiteIdMismatchError is
        re-raised — the controller maps it to 409.
        """
        try:
            history = await self.ensure_conversation(req)
            turn = await self._agent_instance().chat_turn(
                req.message, message_history=history
            )
            await self._store_instance().append_messages(
                req.conversation_id, turn.new_messages
            )
        except SiteIdMismatchError:
            raise
        except Exception:
            log.exception("analyst turn failed")
            return _error_message()
        else:
            return turn.message

    async def stream_turn(
        self, req: AnalystChatRequest, history: list[ModelMessage]
    ) -> AsyncIterator[bytes]:
        """Stream one turn as SSE frames — live tool events then a terminal.

        `tool_start` / `tool_end` per tool call, then `message` (the full
        AnalystMessage) and `done`. `history` is supplied by the caller,
        which has already run `ensure_conversation` (so a siteId 409 is
        handled before the stream opens). Any failure mid-stream emits an
        error `message` + `done{status:error}` — never an HTTP 500.
        """
        store = self._store_instance()
        try:
            stream = self._agent_instance().chat_turn_stream(
                req.message, message_history=history
            )
            async for name, payload in stream:
                if name != "result":
                    yield _sse(name, payload)
                    continue
                assert isinstance(payload, ChatTurnResult)
                await store.append_messages(req.conversation_id, payload.new_messages)
                yield _sse("message", payload.message.model_dump(by_alias=True))
                yield _sse("done", {"status": payload.status})
        except Exception:
            log.exception("analyst stream failed")
            yield _sse("message", _error_message().model_dump(by_alias=True))
            yield _sse("done", {"status": "error"})


def _error_message() -> AnalystMessage:
    """Apologetic AnalystMessage with a ToolError artifact instead of 500."""
    return AnalystMessage.model_validate(
        {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "I hit a snag handling that — the model or one of its "
                        "tools failed. Try again in a moment, or rephrase. "
                        "If it keeps happening let the team know."
                    ),
                },
                {
                    "type": "artifact",
                    "artifact": {
                        "kind": "error",
                        "spec": {
                            "code": "unknown",
                            "message": "agent turn failed; see server logs",
                            "dataAsOf": datetime.now(UTC).strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            ),
                        },
                    },
                },
            ],
        }
    )
