"""Ollama-backed graphiti clients for the local/airgapped Neo4j path.

Mirrors graphiti_bedrock.py shape. Wraps our OllamaQwen3Embedder so
graphiti sees the Matryoshka-truncated 1024d vector (ADR-024 schema)
instead of qwen3-embedding:4b's native 2560d.

LLM + reranker reuse graphiti's stock OpenAI clients pointed at the
Ollama /v1 base URL — Ollama exposes the OpenAI-compatible chat
completions endpoint that both clients speak.
"""

from collections.abc import Iterable

from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.embedder.client import EmbedderClient, EmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

from .embedder import EMBEDDING_DIM, OllamaQwen3Embedder


class OllamaEmbedderClient(EmbedderClient):
    """qwen3-embedding:4b via Ollama, truncated to 1024d for ADR-024 parity."""

    def __init__(self, base_url: str, model: str = "qwen3-embedding:4b") -> None:
        """Wrap our existing truncating embedder for graphiti's protocol."""
        self.config = EmbedderConfig(embedding_dim=EMBEDDING_DIM)
        self._inner = OllamaQwen3Embedder(base_url=base_url, model=model)

    async def create(
        self,
        input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]],
    ) -> list[float]:
        """Graphiti always passes str or list[str] in practice."""
        if isinstance(input_data, str):
            return await self._inner.embed(input_data)
        if (
            isinstance(input_data, list)
            and input_data
            and isinstance(input_data[0], str)
        ):
            # Match BedrockEmbedderClient: single combined embedding for list input.
            strs: list[str] = [s for s in input_data if isinstance(s, str)]
            return await self._inner.embed(" ".join(strs))
        raise TypeError(f"unsupported input_data type: {type(input_data).__name__}")

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        """Per-item embed — Ollama has no batch endpoint."""
        return [await self._inner.embed(t) for t in input_data_list]


def make_ollama_llm(base_url: str, model: str) -> OpenAIGenericClient:
    """Graphiti's OpenAI client pointed at Ollama's /v1/chat/completions.

    api_key is required by the OpenAI SDK but ignored by Ollama — any
    placeholder works.
    """
    return OpenAIGenericClient(
        config=LLMConfig(api_key="ollama", base_url=base_url, model=model)
    )


def make_ollama_reranker(base_url: str, model: str) -> OpenAIRerankerClient:
    """Reranker uses the same chat endpoint as the LLM client."""
    return OpenAIRerankerClient(
        config=LLMConfig(api_key="ollama", base_url=base_url, model=model)
    )
