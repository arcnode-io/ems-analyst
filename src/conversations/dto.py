"""DTOs for /analyst/chat.

Body shape mirrors the HMI handoff (camelCase JSON, snake_case Python).
Response is the agent's AnalystMessage verbatim.
"""

from pydantic import BaseModel, ConfigDict


def _to_camel(snake: str) -> str:
    """foo_bar -> fooBar."""
    head, *tail = snake.split("_")
    return head + "".join(p.capitalize() for p in tail)


class _Camel(BaseModel):
    """Base — camelCase JSON via alias generator."""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class ChatContext(_Camel):
    """Optional client-side hints. siteId is enforced on second+ turns."""

    site_id: str | None = None
    focused_device_id: str | None = None


class AnalystChatRequest(_Camel):
    """POST /analyst/chat body — matches HMI's useAnalystChat hook contract."""

    conversation_id: str
    message: str
    context: ChatContext | None = None
