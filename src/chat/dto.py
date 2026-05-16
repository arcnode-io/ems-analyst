"""Request/response DTOs for /chat."""

from pydantic import BaseModel


class ChatRequestDto(BaseModel):
    """User-provided chat prompt."""

    prompt: str


class ChatResponseDto(BaseModel):
    """Agent's reply text."""

    response: str
