"""MCP server integration for knowledge graph and vector search."""

from typing import Final

from pydantic_ai.mcp import MCPServerStdio

MCP_SERVER_TIMEOUT: Final[int] = 30


def create_mcp_server() -> MCPServerStdio:
    """Spawn the python-mcp-server child with parent-process env passthrough.

    The child reads its backend selection from env vars at startup:
      - GRAPH_URL → Neo4j / Aura (commercial)
      - NEPTUNE_HOST + AOSS_HOST → Neptune + AOSS (defense)
      - VECTOR_URL → pgvector (both variants)
    MCPServerStdio inherits this process's env by default — compose populates
    it via env_file, tests set env vars directly. No explicit env override.
    """
    return MCPServerStdio(
        command="python",
        args=["-m", "python_mcp_server"],
        timeout=MCP_SERVER_TIMEOUT,
    )
