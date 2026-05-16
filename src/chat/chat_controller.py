"""POST /chat — agent-backed conversational endpoint."""

from classy_fastapi import Routable, post

from .chat_service import ChatService
from .dto import ChatRequestDto, ChatResponseDto


class ChatController(Routable):
    """Routes the /chat POST through to ChatService.chat()."""

    def __init__(self, chat_service: ChatService) -> None:
        super().__init__()
        self.chat_service = chat_service

    @post(
        "/chat",
        response_model=ChatResponseDto,
        tags=["Chat"],
        responses={200: {"description": "Agent reply"}},
    )
    async def chat(self, body: ChatRequestDto) -> ChatResponseDto:
        """Send `prompt` to the analyst agent, return its reply."""
        reply = self.chat_service.chat(body.prompt)
        return ChatResponseDto(response=reply)
