"""Orchestrates conversation store + ems_analyst_agent.Agent for one turn."""

import os

from ems_analyst_agent.lib import Agent
from ems_analyst_agent.schemas import AnalystMessage

from .conversation_store import ConversationStore, SiteIdMismatchError
from .dto import AnalystChatRequest

_VECTOR_URL_ENV: str = "VECTOR_URL"
_SITE_ID_ENV: str = "SITE_ID"


class ConversationService:
    """One agent turn end-to-end with thread persistence + siteId enforcement."""

    def __init__(self) -> None:
        """Lazy singletons — first request spawns the agent + checks the DB."""
        self._agent: Agent | None = None
        self._store: ConversationStore | None = None

    def _agent_instance(self) -> Agent:
        if self._agent is None:
            self._agent = Agent()
        return self._agent

    def _store_instance(self) -> ConversationStore:
        if self._store is None:
            self._store = ConversationStore(postgres_url=os.environ[_VECTOR_URL_ENV])
        return self._store

    async def handle_turn(self, req: AnalystChatRequest) -> AnalystMessage:
        """Run one turn — load thread, call agent, persist trace.

        Validates request.context.siteId in two layers:
        1. Against the server's baked SITE_ID env (per-deployment, CFN-baked).
           Mismatch = misrouted client → 409.
        2. Against the first-turn siteId stored on the conversation.
           Mismatch = conversation hijack / replay → 409.
        Both surface as the same `code='site_id_changed'` per HMI handoff.

        Raises:
            SiteIdMismatchError: on either layer's mismatch.
        """
        store = self._store_instance()
        request_site = req.context.site_id if req.context else None
        baked_site = os.environ.get(_SITE_ID_ENV)
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
