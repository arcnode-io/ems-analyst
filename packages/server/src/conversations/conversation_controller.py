"""POST /analyst/chat — the multi-turn analyst chat endpoint.

Content-negotiated: `Accept: text/event-stream` streams the turn as SSE
(live tool-trace events then a terminal message); any other Accept
returns the final AnalystMessage as JSON. One endpoint, one contract.
"""

from typing import Annotated

from classy_fastapi import Routable, post
from ems_analyst_agent.schemas import AnalystMessage
from fastapi import Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic_ai.messages import ModelMessage

from ..rate_limit import limiter
from .conversation_service import ConversationService
from .conversation_store import SiteIdMismatchError
from .dto import AnalystChatRequest

# LLM-backed — each call is a real gemma4:26b turn (tool calls + tokens),
# the actual cost/abuse surface on an unauthenticated endpoint. Generous
# for real interactive use (nobody chats faster than this), tight enough
# to cap a runaway script.
_CHAT_RATE_LIMIT: str = "20/minute"


@limiter.limit(_CHAT_RATE_LIMIT)
async def _check_chat_rate_limit(request: Request) -> None:
    """Rate-limit gate for POST /analyst/chat — called explicitly, not a route.

    slowapi's decorator assumes it's wrapping a plain function whose own
    `args` tuple matches its signature positionally. classy_fastapi binds
    routes as functools.partial(method, self), so `self` occupies args[0]
    and slowapi's request lookup indexes past the end of `args`
    (IndexError) if `@limiter.limit` decorates the route method directly.
    A standalone function keeps that assumption true; it raises
    RateLimitExceeded internally on breach, which propagates up through
    the caller exactly as if the decorator sat on the route itself —
    caught by the same app-level exception handler either way.
    """


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
            200: {"description": "Assistant turn — JSON, or SSE if streamed"},
            409: {"description": "siteId changed mid-conversation"},
        },
    )
    async def chat(
        self,
        request: Request,
        body: AnalystChatRequest,
        accept: Annotated[str, Header()] = "",
    ) -> AnalystMessage | StreamingResponse:
        """Multi-turn analyst chat — JSON, or SSE stream on Accept negotiation."""
        await _check_chat_rate_limit(request)
        if "text/event-stream" in accept.lower():
            # Validate siteId before the stream opens — once a
            # StreamingResponse starts it has committed HTTP 200, so a
            # 409 is no longer possible.
            history = await self._ensure_or_409(body)
            return StreamingResponse(
                self.service.stream_turn(body, history),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache"},
            )
        try:
            return await self.service.handle_turn(body)
        except SiteIdMismatchError as e:
            raise self._conflict(e) from e

    async def _ensure_or_409(self, body: AnalystChatRequest) -> list[ModelMessage]:
        """Run siteId validation; convert a mismatch to HTTP 409."""
        try:
            return await self.service.ensure_conversation(body)
        except SiteIdMismatchError as e:
            raise self._conflict(e) from e

    @staticmethod
    def _conflict(e: SiteIdMismatchError) -> HTTPException:
        """409 — hard-invalidate the conversation; the HMI mints a new id."""
        return HTTPException(
            status_code=409,
            detail={"code": "site_id_changed", "message": str(e)},
        )
