"""MCP server integration for knowledge graph and vector search."""

import os
from typing import Final

from pydantic_ai.mcp import MCPServerStdio

# MCP server configuration
MCP_SERVER_TIMEOUT: Final[int] = 30


def create_mcp_server(
    neo4j_url: str, postgres_url: str, neo4j_password: str
) -> MCPServerStdio:
    """Create and configure MCP server for knowledge graph access.

    Args:
        neo4j_url: Neo4j bolt connection URL
        postgres_url: PostgreSQL connection URL for vector search
        neo4j_password: Neo4j database password

    Returns:
        Configured MCPServerStdio instance

    Example:
        >>> server = create_mcp_server(
        ...     "bolt://localhost:7687",
        ...     "postgresql://user:pass@localhost:5432/db",
        ...     "password"
        ... )
        >>> # Server can now be used as agent toolset

    """
    # Set environment variables for MCP server
    env = os.environ.copy()
    env["NEO4J_PASSWORD"] = neo4j_password
    env["POSTGRES_URL"] = postgres_url
    env["NEO4J_URI"] = neo4j_url
    env["NEO4J_USER"] = "neo4j"
    env["NEO4J_DATABASE"] = "neo4j"

    # Create MCP server connection to python-mcp-server
    # Reason: Using -m flag to run as Python module instead of installed script
    server = MCPServerStdio(
        command="uv",
        args=["run", "--project", "../python-mcp-server", "-m", "python_mcp_server"],
        timeout=MCP_SERVER_TIMEOUT,
        env=env,
    )

    return server
