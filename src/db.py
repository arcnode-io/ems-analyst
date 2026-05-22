"""Shared asyncpg connection helper.

One short-lived connection per query, guaranteed-closed. Services and
the conversation store all open through `connect` rather than repeating
the connect / try / finally-close dance.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg


@asynccontextmanager
async def connect(url: str) -> AsyncIterator[asyncpg.Connection]:
    """Yield an asyncpg connection to `url`, closed on exit."""
    conn = await asyncpg.connect(url)
    try:
        yield conn
    finally:
        await conn.close()
