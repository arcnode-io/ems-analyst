"""POST /analyst/chat — multi-turn analyst chat endpoint per HMI handoff."""

from classy_fastapi import Routable, post
from ems_analyst_agent.schemas import AnalystMessage
from fastapi import HTTPException

from .conversation_service import ConversationService
from .conversation_store import SiteIdMismatchError
from .dto import AnalystChatRequest


class ConversationController(Routable):
    """Routes the /analyst/chat POST through to ConversationService."""

    def __init__(self, service: ConversationService) -> None:
        super().__init__()
        self.service = service

    @post(
        "/analyst/chat",
        response_model=AnalystMessage,
        tags=["Analyst"],
        responses={
            200: {"description": "Assistant turn — text + 0..N artifacts"},
            409: {"description": "siteId changed mid-conversation"},
        },
    )
    async def chat(self, body: AnalystChatRequest) -> AnalystMessage:
        """Multi-turn analyst chat. See /tmp/HANDOFF-analyst-backend.md."""
        try:
            return await self.service.handle_turn(body)
        except SiteIdMismatchError as e:
            # Per HMI handoff Q2 — invalidate the conversation hard, don't
            # try to recover. HMI mints a new conversationId on next send.
            raise HTTPException(
                status_code=409,
                detail={"code": "site_id_changed", "message": str(e)},
            ) from e
