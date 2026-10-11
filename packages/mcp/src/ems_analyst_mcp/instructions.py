"""Guidance text the MCP server exposes (resources + prompt).

Pure functions of one flag: whether a graph backend is configured. With
none, the graph tools (search_knowledge / verify_fact / combined_search)
aren't registered, so guidance must not send a client to them — a
deployment without a graph used to be told "ALWAYS call verify_fact
first" about a tool that only ever raised.
"""


def knowledge_instructions(graph: bool) -> str:
    """How to answer accurately using this knowledge base."""
    if not graph:
        return """
        HOW TO USE THIS KNOWLEDGE BASE EFFECTIVELY:

        Step 1: Use rag_search for explanations, specs and standards.
        Step 2: Cite your sources clearly: [Documents].
        Step 3: If evidence is absent or weak, say so — do not guess.
        """
    return """
        HOW TO USE THIS KNOWLEDGE BASE EFFECTIVELY:

        Step 1: ALWAYS verify facts before stating them — call verify_fact
                and judge the returned evidence yourself.
        Step 2: Use search_knowledge for entities and relationships.
        Step 3: Use rag_search for detailed explanations.
        Step 4: Combine results for complete answers.
        Step 5: Cite your sources clearly: [Graph] or [Documents].
        Step 6: If evidence is absent or weak, say so — do not guess.
        """


def example_queries(graph: bool) -> str:
    """Example patterns for effective knowledge retrieval."""
    if not graph:
        return """
        EXAMPLE USAGE PATTERNS:

        1. "Explain how Z works"
           → rag_search("how Z works")

        2. "What does the standard require for X?"
           → rag_search("X requirements")
        """
    return """
        EXAMPLE USAGE PATTERNS:

        1. "What is the relationship between X and Y?"
           → search_knowledge("X Y relationship")

        2. "Explain how Z works"
           → search_knowledge("Z") + rag_search("how Z works")

        3. "Is it true that <claim>?"
           → verify_fact("<claim>"), then judge evidence

        4. Complex question needing both facts and context:
           → combined_search(query)
        """


def verification_prompt(graph: bool) -> str:
    """Template for answering with evidence-grounded verification."""
    if not graph:
        return """
        To answer any question accurately:

        1. IDENTIFY the key claims.
        2. Use rag_search() for supporting documents.
        3. SYNTHESIZE with citations [Documents].
        4. State clearly when evidence is missing rather than guessing.
        """
    return """
        To answer any question accurately:

        1. IDENTIFY key entities and claims.
        2. For each claim call verify_fact() and inspect the evidence.
        3. Use search_knowledge() for structured facts.
        4. Use rag_search() for supporting documents.
        5. SYNTHESIZE with citations [Graph] or [Documents].
        6. State clearly when evidence is missing rather than guessing.
        """
