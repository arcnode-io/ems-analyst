"""asyncpg-backed conversation persistence.

Mirrors ems_analyst_agent.memory.MemoryService — raw asyncpg, lazy
CREATE TABLE on first call, no migration framework.

Two tables:
  conversations(id UUID PK, site_id TEXT, created_at TIMESTAMPTZ)
  conversation_messages(id BIGSERIAL PK, conversation_id UUID FK,
                        position INT, payload JSONB, created_at)

Payload is the full pydantic-ai ModelMessage JSON (lossless — tool
calls + returns preserved) so subsequent turns can replay context.
"""

import json
import logging

import asyncpg
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

log = logging.getLogger(__name__)


class SiteIdMismatchError(Exception):
    """First-turn siteId differs from current request's. Caller returns 409."""


class ConversationStore:
    """Persists chat threads keyed by HMI-generated conversationId."""

    def __init__(self, postgres_url: str) -> None:
        """Wrap a Postgres URL. Lazy schema setup on first call."""
        self.postgres_url = postgres_url
        self._tables_ready = False

    async def _ensure_tables(self) -> None:
        """CREATE TABLE IF NOT EXISTS for both tables + index."""
        if self._tables_ready:
            return
        conn = await asyncpg.connect(self.postgres_url)
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id UUID PRIMARY KEY,
                    site_id TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id BIGSERIAL PRIMARY KEY,
                    conversation_id UUID NOT NULL
                        REFERENCES conversations(id) ON DELETE CASCADE,
                    position INT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS conv_msg_thread_idx
                    ON conversation_messages (conversation_id, position)
            """)
        finally:
            await conn.close()
        self._tables_ready = True

    async def get_site_id(self, conversation_id: str) -> str | None:
        """Return the conversation's siteId, or None if it doesn't exist."""
        await self._ensure_tables()
        conn = await asyncpg.connect(self.postgres_url)
        try:
            row = await conn.fetchrow(
                "SELECT site_id FROM conversations WHERE id = $1::uuid",
                conversation_id,
            )
        finally:
            await conn.close()
        return None if row is None else str(row["site_id"])

    async def create(self, conversation_id: str, site_id: str) -> None:
        """First-turn insert. Caller already confirmed the row didn't exist."""
        await self._ensure_tables()
        conn = await asyncpg.connect(self.postgres_url)
        try:
            await conn.execute(
                "INSERT INTO conversations (id, site_id) VALUES ($1::uuid, $2)",
                conversation_id,
                site_id,
            )
        finally:
            await conn.close()

    async def load_history(self, conversation_id: str) -> list[ModelMessage]:
        """Replay the thread in position order — returns pydantic-ai messages."""
        await self._ensure_tables()
        conn = await asyncpg.connect(self.postgres_url)
        try:
            rows = await conn.fetch(
                "SELECT payload FROM conversation_messages "
                "WHERE conversation_id = $1::uuid ORDER BY position",
                conversation_id,
            )
        finally:
            await conn.close()
        if not rows:
            return []
        # Each row is a single ModelMessage serialised — concat and let the
        # type adapter validate the whole list at once for fewer round-trips.
        raw = "[" + ",".join(str(r["payload"]) for r in rows) + "]"
        return list(ModelMessagesTypeAdapter.validate_json(raw))

    async def append_messages(
        self, conversation_id: str, new_messages: list[ModelMessage]
    ) -> None:
        """Persist new pydantic-ai messages at the tail of the thread."""
        if not new_messages:
            return
        await self._ensure_tables()
        conn = await asyncpg.connect(self.postgres_url)
        try:
            next_pos = await conn.fetchval(
                "SELECT COALESCE(MAX(position), -1) + 1 "
                "FROM conversation_messages WHERE conversation_id = $1::uuid",
                conversation_id,
            )
            payloads = [
                json.loads(ModelMessagesTypeAdapter.dump_json([m]))[0]
                for m in new_messages
            ]
            rows = [
                (conversation_id, next_pos + i, json.dumps(payload))
                for i, payload in enumerate(payloads)
            ]
            await conn.executemany(
                "INSERT INTO conversation_messages "
                "(conversation_id, position, payload) "
                "VALUES ($1::uuid, $2, $3::jsonb)",
                rows,
            )
        finally:
            await conn.close()
