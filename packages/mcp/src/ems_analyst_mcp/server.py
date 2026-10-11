"""MCP server with FastMCP."""

from typing import Optional

from mcp.server.fastmcp import FastMCP

from .clients import GraphitiClient, RAGClient, make_embedder
from .config import Config, load_config
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

    @mcp.tool()
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

    @mcp.tool()
    async def rag_search(query: str, limit: int = 10) -> list[Document]:
        """Search the complete markdown corpus using vector + lexical retrieval.

        USE WHEN: Self-contained spec lookups, protocol fields/function codes,
        numeric facts, explanations, and supporting source passages.
        This is the default retrieval path for most domain questions.
        The query string is embedded internally; no pre-computed vector needed.
        """
        client = RAGClient.from_env(embedder=embedder)
        return await client.search(query, limit)

    @mcp.tool()
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

    @mcp.tool()
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

    @mcp.resource("knowledge://instructions")
    async def knowledge_instructions() -> str:
        """How to answer accurately using this knowledge base."""
        return """
        HOW TO USE THIS KNOWLEDGE BASE EFFECTIVELY:

        Step 1: Ground every claim in retrieved evidence.
        Step 2: Use rag_search for self-contained lookups and source passages.
        Step 3: Use search_knowledge / verify_fact for cross-document standard
                supersession and multi-hop BESS chapter-5 control/incident chains.
        Step 4: Use combined_search when those graph questions also need context.
        Step 5: Cite your sources clearly: [Graph] or [Documents].
        Step 6: If evidence is absent or weak, say so — do not guess.
        """

    @mcp.resource("knowledge://examples")
    async def example_queries() -> str:
        """Example patterns for effective knowledge retrieval."""
        return """
        EXAMPLE USAGE PATTERNS:

        1. "What replaced CIP-006-7?"
           → search_knowledge("CIP-006-7 superseded by")

        2. "What Modbus function code implements Mask Write Register?"
           → rag_search("Modbus Mask Write Register function code")

        3. "How do BMS, EMS, PPC/SCADA, and fleet controls coordinate?"
           → combined_search("BESS BMS EMS PPC SCADA fleet control hierarchy")

        4. "Did limited telemetry contribute to the Victorian Big Battery fire?"
           → verify_fact("Victorian Big Battery commissioning telemetry fire")
        """

    @mcp.prompt("answer_with_verification")
    async def answer_with_verification() -> str:
        """Template for answering with evidence-grounded verification."""
        return """
        To answer any question accurately:

        1. IDENTIFY key entities and claims.
        2. Use rag_search() for flat lookups and supporting source passages.
        3. Use search_knowledge() / verify_fact() for cross-document supersession
           or BESS chapter-5 control/incident chains, and inspect the evidence.
        4. Use combined_search() when those graph questions also need documents.
        5. SYNTHESIZE with citations [Graph] or [Documents].
        6. State clearly when evidence is missing rather than guessing.
        """

    return mcp
