"""MCP server integration for knowledge graph and vector search."""

import os
from typing import Final

from fastmcp.client.transports import StdioTransport
from pydantic_ai.mcp import MCPToolset

MCP_SERVER_TIMEOUT: Final[int] = 30


def create_mcp_server() -> MCPToolset:
    """Spawn the ems-analyst-mcp child as an MCP toolset.

    The child reads its backend selection from env vars at startup:
      - GRAPH_URL → Neo4j selfhosted / Aura (commercial)
      - NEPTUNE_HOST + AOSS_HOST → Neptune + AOSS (defense)
      - VECTOR_URL → pgvector (both variants)
    Compose populates these via env_file; tests set them directly.

    `StdioTransport(env=os.environ.copy())` is required: the child
    otherwise inherits nothing from the parent, so GRAPH_URL/VECTOR_URL
    never reach it and the client falls back to localhost defaults.
    """
    return MCPToolset(
        StdioTransport(
            command="python",
            args=["-m", "ems_analyst_mcp"],
            env=os.environ.copy(),
        ),
        init_timeout=MCP_SERVER_TIMEOUT,
    )
