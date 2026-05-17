"""FastAPI surface for the analyst Agent.

`POST /analyst/chat` accepts the HMI contract from
`/tmp/HANDOFF-analyst-backend.md` and returns a full `AnalystMessage`
JSON (text + 0..N artifacts).

v1 is JSON-only. SSE streaming per the handoff is deferred to v1.1.
"""

from collections.abc import Callable
from typing import Protocol

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from .schemas import AnalystMessage


def _to_camel(snake: str) -> str:
    head, *tail = snake.split("_")
    return head + "".join(p.capitalize() for p in tail)


class _Camel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class _AnalystAgent(Protocol):
    """Structural type — anything with `chat_message()` works.

    Reason: lets us test the HTTP layer with a fake agent without
    pulling in MemoryService + LLM at unit-test time.
    """

    async def chat_message(self, prompt: str) -> AnalystMessage: ...


class ChatContext(_Camel):
    """Optional client-side hints. Mirrors HMI handoff."""

    site_id: str | None = None
    focused_device_id: str | None = None


class ChatRequest(_Camel):
    """`POST /analyst/chat` request body."""

    conversation_id: str
    message: str
    context: ChatContext | None = None


def build_app(agent_factory: Callable[[], _AnalystAgent]) -> FastAPI:
    """Build the FastAPI app.

    Args:
        agent_factory: Returns an Agent instance per request — keeps test
            doubles trivial to inject. Production callers pass `Agent`.
    """
    app = FastAPI(title="ems-analyst-agent", version="1.0.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/analyst/chat", response_model=AnalystMessage)
    async def chat(req: ChatRequest) -> AnalystMessage:
        # TODO: route conversation_id to a persistent thread store
        # (in-memory MemoryService for now). HMI handoff Q1 covers retention.
        # TODO: enforce siteId consistency once we persist the first-turn site
        # (HMI handoff reply Q2 — return 409 site_id_changed on mismatch).
        agent = agent_factory()
        return await agent.chat_message(req.message)

    return app
