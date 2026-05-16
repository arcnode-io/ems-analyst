"""Wires ChatService → ChatController → router for AppModule."""

from .chat_controller import ChatController
from .chat_service import ChatService


class ChatModule:
    """Construct the chat router with its agent-backed service."""

    def __init__(self) -> None:
        chat_service = ChatService()
        self.router = ChatController(chat_service).router
