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

        Step 1: Ground every claim in retrieved evidence.
        Step 2: Use rag_search for self-contained lookups and source passages.
        Step 3: Use search_knowledge / verify_fact for cross-document standard
                supersession and multi-hop BESS chapter-5 control/incident chains.
        Step 4: Use combined_search when those graph questions also need context.
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

        1. "What replaced CIP-006-7?"
           → search_knowledge("CIP-006-7 superseded by")

        2. "What Modbus function code implements Mask Write Register?"
           → rag_search("Modbus Mask Write Register function code")

        3. "How do BMS, EMS, PPC/SCADA, and fleet controls coordinate?"
           → combined_search("BESS BMS EMS PPC SCADA fleet control hierarchy")

        4. "Did limited telemetry contribute to the Victorian Big Battery fire?"
           → verify_fact("Victorian Big Battery commissioning telemetry fire")
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
        2. Use rag_search() for flat lookups and supporting source passages.
        3. Use search_knowledge() / verify_fact() for cross-document supersession
           or BESS chapter-5 control/incident chains, and inspect the evidence.
        4. Use combined_search() when those graph questions also need documents.
        5. SYNTHESIZE with citations [Graph] or [Documents].
        6. State clearly when evidence is missing rather than guessing.
        """
