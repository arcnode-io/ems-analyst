"""Entry point: `python -m ems_analyst_agent` boots the FastAPI server."""

import uvicorn

from .lib import Agent
from .server import build_app

if __name__ == "__main__":
    # Singleton agent for the process — pydantic-ai PydanticAgent is reusable.
    agent = Agent()
    app = build_app(agent_factory=lambda: agent)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")  # noqa: S104
