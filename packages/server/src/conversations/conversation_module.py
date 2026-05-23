"""Wires ConversationService → ConversationController for AppModule."""

from .conversation_controller import ConversationController
from .conversation_service import ConversationService


class ConversationModule:
    """Construct the /analyst/chat router with its service."""

    def __init__(self) -> None:
        """Lazy: actual Agent + store spawn on first request."""
        self.router = ConversationController(ConversationService()).router
