"""Memory service for storing and retrieving conversations with semantic search."""

import asyncpg
from typing import Final

from pgvector.asyncpg import register_vector

from ..config import load_config

# Embedding dimensions for different providers
OPENAI_EMBEDDING_DIM: Final[int] = 1536
NOMIC_EMBEDDING_DIM: Final[int] = 768


class MemoryService:
    """Service for storing and retrieving semantic memories."""

    def __init__(self, postgres_url: str) -> None:
        """Initialize the memory service.

        Args:
            postgres_url: PostgreSQL connection URL with pgvector extension

        """
        self.postgres_url = postgres_url
        self.config = load_config()

    async def store_memory(self, content: str, embedding: list[float]) -> None:
        """Store a memory with its embedding in the database.

        Args:
            content: The text content to store
            embedding: The embedding vector for the content

        Example:
            >>> service = MemoryService("postgresql://...")
            >>> await service.store_memory("User likes blue", [0.1, 0.2, ...])

        """
        conn = await asyncpg.connect(self.postgres_url)
        try:
            # Register vector type
            await register_vector(conn)

            # Insert the memory
            await conn.execute(
                """
                INSERT INTO conversation_memory (content, embedding)
                VALUES ($1, $2)
                """,
                content,
                embedding,
            )
        finally:
            await conn.close()

    async def search_memories(
        self, query_embedding: list[float], limit: int = 5
    ) -> list[str]:
        """Search for relevant memories using vector similarity.

        Args:
            query_embedding: The embedding vector for the search query
            limit: Maximum number of memories to return

        Returns:
            List of relevant memory contents, ordered by similarity

        Example:
            >>> service = MemoryService("postgresql://...")
            >>> memories = await service.search_memories([0.1, 0.2, ...], limit=3)
            >>> print(memories)
            ['User likes blue', 'User prefers tea', ...]

        """
        conn = await asyncpg.connect(self.postgres_url)
        try:
            # Register vector type
            await register_vector(conn)

            # Search for similar memories using cosine distance
            # Reason: Lower distance = more similar
            rows = await conn.fetch(
                """
                SELECT content
                FROM conversation_memory
                ORDER BY embedding <-> $1
                LIMIT $2
                """,
                query_embedding,
                limit,
            )

            return [row["content"] for row in rows]
        finally:
            await conn.close()

    async def generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for text using the configured provider.

        Args:
            text: The text to embed

        Returns:
            Embedding vector as list of floats

        Example:
            >>> service = MemoryService("postgresql://...")
            >>> embedding = await service.generate_embedding("Hello world")
            >>> len(embedding)
            1536

        """
        if self.config.embedding_provider == "openai":
            return await self._generate_openai_embedding(text)
        else:
            return await self._generate_nomic_embedding(text)

    async def _generate_openai_embedding(self, text: str) -> list[float]:
        """Generate embedding using OpenAI API.

        Args:
            text: The text to embed

        Returns:
            1536-dimensional embedding vector

        """
        import os
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = await client.embeddings.create(
            model=self.config.embedding_model, input=text
        )
        return response.data[0].embedding

    async def _generate_nomic_embedding(self, text: str) -> list[float]:
        """Generate embedding using Nomic local embeddings.

        Args:
            text: The text to embed

        Returns:
            768-dimensional embedding vector

        """
        import nomic

        # Reason: Nomic provides local embeddings without API calls
        result = nomic.embed.text([text], model=self.config.embedding_model)  # type: ignore[attr-defined]
        return result["embeddings"][0]  # type: ignore[no-any-return]
