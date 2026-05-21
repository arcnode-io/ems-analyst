"""Orchestrates conversation store + ems_analyst_agent.Agent for one turn."""

import logging
import os
from datetime import UTC, datetime

from ems_analyst_agent.lib import Agent
from ems_analyst_agent.schemas import AnalystMessage

from .conversation_store import ConversationStore, SiteIdMismatchError
from .dto import AnalystChatRequest

log = logging.getLogger(__name__)

_VECTOR_URL_ENV: str = "VECTOR_URL"


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

    async def handle_turn(self, req: AnalystChatRequest) -> AnalystMessage:
        """Run one turn — load thread, call agent, persist trace.

        Validates request.context.siteId in two layers:
        1. Against the server's baked SITE_ID env (per-deployment, CFN-baked).
           Mismatch = misrouted client → 409.
        2. Against the first-turn siteId stored on the conversation.
           Mismatch = conversation hijack / replay → 409.
        Both surface as the same `code='site_id_changed'` per HMI handoff.

        Raises:
            SiteIdMismatchError: on either layer's mismatch (→ HTTP 409).
        """
        # The whole turn — store setup, conversation DB I/O, agent call —
        # is wrapped. Any infra failure (Postgres unreachable, VECTOR_URL
        # unset, MCP child crash, Ollama timeout, Bedrock 503) degrades to
        # a 200 error-artifact per the HMI brief; never an HTTP 500. Only
        # SiteIdMismatchError is re-raised — the controller maps it to 409.
        try:
            return await self._run_turn(req)
        except SiteIdMismatchError:
            raise
        except Exception:
            log.exception("analyst turn failed")
            return _error_message()

    async def _run_turn(self, req: AnalystChatRequest) -> AnalystMessage:
        """The turn proper — siteId checks, store I/O, agent call.

        Raises freely; `handle_turn` is the error boundary that catches
        everything except SiteIdMismatchError.
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

        history = await store.load_history(req.conversation_id)
        turn = await self._agent_instance().chat_turn(
            req.message, message_history=history
        )
        await store.append_messages(req.conversation_id, turn.new_messages)
        return turn.message


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
