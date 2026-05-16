"""Memory service for storing and retrieving conversations with semantic search.

Embedding provider mirrors python-mcp-server's Embedder abstraction
(Bedrock Titan for cloud, Ollama Qwen3 for airgapped) so cloud and
airgapped deployments need ZERO third-party API keys per ADR-024.
OpenAI is gone — see [[portal-self-serve]].
"""

import asyncpg
from pgvector.asyncpg import register_vector
from python_mcp_server.clients import EMBEDDING_DIM, Embedder


class MemoryService:
    """Service for storing and retrieving semantic memories.

    Embedder is dependency-injected so the per-customer provider
    (Bedrock or Ollama) is decided once at Agent construction time.
    """

    def __init__(self, postgres_url: str, embedder: Embedder) -> None:
        """Initialize the memory service.

        Args:
            postgres_url: PostgreSQL connection URL with pgvector extension
            embedder: 1024d embedding provider (BedrockTitan or OllamaQwen3)
        """
        self.postgres_url = postgres_url
        self.embedder = embedder
        self._table_ready = False

    async def _ensure_table(self) -> None:
        """Self-managed schema — agent owns conversation_memory.

        Created lazily on first store/search. CREATE TABLE IF NOT EXISTS
        keeps it idempotent across restarts.
        """
        if self._table_ready:
            return
        conn = await asyncpg.connect(self.postgres_url)
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS conversation_memory ("
                "id SERIAL PRIMARY KEY, "
                "content TEXT NOT NULL, "
                f"embedding vector({EMBEDDING_DIM}) NOT NULL, "
                "created_at TIMESTAMPTZ DEFAULT now())"
            )
        finally:
            await conn.close()
        self._table_ready = True

    async def store_memory(self, content: str, embedding: list[float]) -> None:
        """Store a memory with its embedding in the database."""
        await self._ensure_table()
        conn = await asyncpg.connect(self.postgres_url)
        try:
            await register_vector(conn)
            await conn.execute(
                "INSERT INTO conversation_memory (content, embedding) "
                "VALUES ($1, $2)",
                content,
                embedding,
            )
        finally:
            await conn.close()

    async def search_memories(
        self, query_embedding: list[float], limit: int = 5
    ) -> list[str]:
        """Search for relevant memories using cosine vector similarity."""
        await self._ensure_table()
        conn = await asyncpg.connect(self.postgres_url)
        try:
            await register_vector(conn)
            # Reason: <-> is cosine distance; lower = more similar.
            rows = await conn.fetch(
                "SELECT content FROM conversation_memory "
                "ORDER BY embedding <-> $1 LIMIT $2",
                query_embedding,
                limit,
            )
            return [row["content"] for row in rows]
        finally:
            await conn.close()

    async def generate_embedding(self, text: str) -> list[float]:
        """Generate a 1024d embedding via the injected provider."""
        return await self.embedder.embed(text)
