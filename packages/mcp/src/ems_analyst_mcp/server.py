"""MCP server with FastMCP."""

from typing import Optional

from mcp.server.fastmcp import FastMCP

from .clients import GraphitiClient, RAGClient, make_embedder
from .config import Config, NoneGraph, load_config
from .instructions import example_queries, knowledge_instructions, verification_prompt
from .models import SearchResults, Document, FactEvidence, CombinedResults


def create_server(config: Optional[Config] = None) -> FastMCP:
    """Create and configure the MCP server.

    Embedder provider is decided by the resolved customer block's
    llm_provider discriminator (Bedrock vs Ollama).

    Backends at request time:
      - GraphitiClient.from_config(server_config) — cfg.graph backend dispatch
      - RAGClient.from_env(embedder) — VECTOR_URL
    """
    server_config = config or load_config()
    embedder = make_embedder(server_config.settings)

    mcp = FastMCP("Knowledge Graph MCP Server")

    async def search_knowledge(query: str, limit: int = 10) -> SearchResults:
        """Search relationships in the scoped knowledge graph (ADR-026).

        USE WHEN: Cross-document standard supersession, or multi-hop BESS
        chapter-5 control/incident chains. Use rag_search for self-contained
        lookups, including protocol fields, function codes, and numeric specs.
        Returns evidence, not a guarantee that a claim is true.
        """
        client = GraphitiClient.from_config(server_config)
        try:
            results = await client.search(query, limit=limit)
            return SearchResults(items=results, total=len(results))
        finally:
            await client.close()

    async def rag_search(query: str, limit: int = 10) -> list[Document]:
        """Search the complete markdown corpus using vector + lexical retrieval.

        USE WHEN: Self-contained spec lookups, protocol fields/function codes,
        numeric facts, explanations, and supporting source passages.
        This is the default retrieval path for most domain questions.
        The query string is embedded internally; no pre-computed vector needed.
        """
        client = RAGClient.from_env(embedder=embedder)
        return await client.search(query, limit)

    async def verify_fact(statement: str, limit: int = 5) -> FactEvidence:
        """Retrieve knowledge-graph evidence relevant to a statement.

        USE WHEN: Checking a cross-document supersession or BESS chapter-5
        control/incident-chain claim. Use rag_search to check other claims.
        Returns related facts; judge whether they support the statement.
        No boolean verdict — entailment is the caller's job.
        """
        client = GraphitiClient.from_config(server_config)
        try:
            evidence = await client.search(statement, limit=limit)
            return FactEvidence(statement=statement, evidence=evidence)
        finally:
            await client.close()

    async def combined_search(query: str, limit: int = 10) -> CombinedResults:
        """Search both the knowledge graph and document vectors.

        USE WHEN: A standard-supersession or BESS control/incident-chain question
        also needs source context. Use rag_search alone for flat spec lookups.
        """
        graph_client = GraphitiClient.from_config(server_config)
        rag_client = RAGClient.from_env(embedder=embedder)
        try:
            graph_results = await graph_client.search(query, limit=limit)
            vector_results = await rag_client.search(query, limit)
            return CombinedResults(
                graph_results=SearchResults(
                    items=graph_results, total=len(graph_results)
                ),
                vector_results=vector_results,
                query=query,
            )
        finally:
            await graph_client.close()

    # Reason: the graph tools raise "no graph backend configured" on a
    # deployment without one — advertising them just burns the model's
    # tool-call budget (and its guidance text told it to call them first).
    graph = not isinstance(server_config.graph, NoneGraph)
    mcp.add_tool(rag_search)
    if graph:
        for graph_tool in (search_knowledge, verify_fact, combined_search):
            mcp.add_tool(graph_tool)

    @mcp.resource("knowledge://instructions")
    async def knowledge_instructions_resource() -> str:
        """How to answer accurately using this knowledge base."""
        return knowledge_instructions(graph)

    @mcp.resource("knowledge://examples")
    async def example_queries_resource() -> str:
        """Example patterns for effective knowledge retrieval."""
        return example_queries(graph)

    @mcp.prompt("answer_with_verification")
    async def answer_with_verification() -> str:
        """Template for answering with evidence-grounded verification."""
        return verification_prompt(graph)

    return mcp
