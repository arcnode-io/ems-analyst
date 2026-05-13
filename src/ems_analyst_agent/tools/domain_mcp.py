"""MCP server integration for knowledge graph and vector search."""

import os
from typing import Final

from pydantic_ai.mcp import MCPServerStdio

MCP_SERVER_TIMEOUT: Final[int] = 30


def create_mcp_server() -> MCPServerStdio:
    """Spawn the python-mcp-server child with parent-process env passthrough.

    The child reads its backend selection from env vars at startup:
      - GRAPH_URL → Neo4j / Aura (commercial)
      - NEPTUNE_HOST + AOSS_HOST → Neptune + AOSS (defense)
      - VECTOR_URL → pgvector (both variants)
    Compose populates these via env_file; tests set them directly.

    `env=os.environ.copy()` is required: pydantic-ai's MCPServerStdio
    defaults `env=None`, which means the subprocess inherits NOTHING from
    the parent. Without this, GRAPH_URL/VECTOR_URL never reach the child
    and the client falls back to localhost defaults.
    """
    return MCPServerStdio(
        command="python",
        args=["-m", "python_mcp_server"],
        timeout=MCP_SERVER_TIMEOUT,
        env=os.environ.copy(),
    )
