"""Analyst-agent library — installed into ems-analyst-server.

Public surface:
- Agent: chat-loop with prompt + memory + tools + render-spec artifacts
- AnalystMessage / AnalystArtifact / LineSpec / BarSpec / TableSpec / PieSpec
  / ToolError: the render-spec contract consumed by ems-hmi via the
  upstream server.
"""

from .config import load_config, setup_logger
from .lib import Agent, AgentDeps, ChatTurnResult
from .schemas import (
    AnalystArtifact,
    AnalystMessage,
    BarSpec,
    LineSpec,
    PieSpec,
    TableSpec,
    ToolError,
)

__all__ = [
    "Agent",
    "AgentDeps",
    "AnalystArtifact",
    "AnalystMessage",
    "BarSpec",
    "ChatTurnResult",
    "LineSpec",
    "PieSpec",
    "TableSpec",
    "ToolError",
    "load_config",
    "setup_logger",
]
