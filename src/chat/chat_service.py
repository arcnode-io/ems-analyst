"""Wraps ems_analyst_agent.Agent for the FastAPI chat endpoint.

Agent construction reads VECTOR_URL + GRAPH_URL (or NEPTUNE_HOST +
AOSS_HOST) from process env, plus OPENAI_API_KEY + OPENWEATHERMAP_API_KEY.
docker-compose env_file mounts /opt/arcnode/secrets.env which carries
those values from CFN-managed Secrets Manager.

Agent construction is lazy — first /chat request triggers spawn of the
python-mcp-server child via stdio. That keeps app boot tolerant of
missing env (tests, dev) while still amortizing the child spawn across
all subsequent requests.
"""

from ems_analyst_agent.lib import Agent


class ChatService:
    """Lazy-singleton Agent wrapper for /chat."""

    def __init__(self) -> None:
        self._agent: Agent | None = None

    def chat(self, prompt: str) -> str:
        """Run the agent against `prompt`, return the text reply."""
        if self._agent is None:
            self._agent = Agent()
        return self._agent.chat(prompt)
