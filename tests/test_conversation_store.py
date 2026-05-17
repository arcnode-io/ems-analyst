"""Integration tests for ConversationStore against a real postgres.

The full HTTP loop (POST /analyst/chat against TestClient + agent) is
intentionally skipped here — running the Agent in tests requires
spawning the MCP child + hitting an LLM, which the agent-side suite
already covers. This file focuses on the store's persistence
guarantees.
"""

import json
import uuid
from collections.abc import Generator

import pytest
import pytest_asyncio
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    UserPromptPart,
)
from testcontainers.postgres import PostgresContainer

from src.conversations.conversation_store import ConversationStore


@pytest.fixture(scope="session")
def postgres_url() -> Generator[str]:
    """Session-scoped Postgres testcontainer — reused across tests."""
    with PostgresContainer(
        "postgres:15", username="postgres", password="testpw", dbname="postgres"
    ) as pg:
        port = int(pg.get_exposed_port(5432))
        yield f"postgres://postgres:testpw@localhost:{port}/postgres"


@pytest_asyncio.fixture
async def store(postgres_url: str) -> ConversationStore:
    """Fresh ConversationStore — tables auto-created on first call."""
    return ConversationStore(postgres_url=postgres_url)


def _user_msg(text: str) -> ModelRequest:
    """Minimal valid pydantic-ai message we can persist + replay."""
    return ModelRequest(parts=[UserPromptPart(content=text)])


class TestConversationStoreRoundTrip:
    """AAA — create, append, load, mismatch detection."""

    @pytest.mark.asyncio
    async def test_get_site_id_returns_none_before_create(
        self, store: ConversationStore
    ) -> None:
        # Arrange
        cid = str(uuid.uuid4())

        # Act + Assert
        assert await store.get_site_id(cid) is None

    @pytest.mark.asyncio
    async def test_create_then_get_returns_site_id(
        self, store: ConversationStore
    ) -> None:
        # Arrange
        cid = str(uuid.uuid4())

        # Act
        await store.create(cid, site_id="site-x")

        # Assert
        assert await store.get_site_id(cid) == "site-x"

    @pytest.mark.asyncio
    async def test_append_and_load_preserves_order_and_payload(
        self, store: ConversationStore
    ) -> None:
        # Arrange
        cid = str(uuid.uuid4())
        await store.create(cid, site_id="site-y")
        msgs = [_user_msg("first"), _user_msg("second"), _user_msg("third")]

        # Act
        await store.append_messages(cid, list(msgs))
        loaded = await store.load_history(cid)

        # Assert — order preserved, content intact
        assert len(loaded) == 3
        loaded_json = json.loads(ModelMessagesTypeAdapter.dump_json(loaded))
        assert loaded_json[0]["parts"][0]["content"] == "first"
        assert loaded_json[2]["parts"][0]["content"] == "third"

    @pytest.mark.asyncio
    async def test_append_extends_existing_thread(
        self, store: ConversationStore
    ) -> None:
        # Arrange
        cid = str(uuid.uuid4())
        await store.create(cid, site_id="site-z")
        await store.append_messages(cid, [_user_msg("a")])

        # Act
        await store.append_messages(cid, [_user_msg("b"), _user_msg("c")])
        loaded = await store.load_history(cid)

        # Assert
        assert len(loaded) == 3
