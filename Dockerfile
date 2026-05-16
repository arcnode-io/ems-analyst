FROM python:3.14-slim AS builder
WORKDIR /app
# git needed: ems-analyst-agent + python-mcp-server are git deps via uv.sources
RUN apt-get update && apt-get install -y --no-install-recommends git postgresql-client && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock .
RUN pip install uv && uv sync --frozen
COPY cfg.yml .
COPY src src
RUN find src -name "test_*.py" -delete

FROM python:3.14-slim AS production
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git postgresql-client && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock .
RUN pip install uv && uv sync --frozen --no-dev --no-install-project
COPY --from=builder /app/src ./src
COPY cfg.yml .
# Seed-then-serve: mcp-server's seed CLI runs to completion (vector +
# graph) BEFORE uvicorn starts. Markers are guaranteed written; chat
# works immediately on first request. Background-seed inside the MCP
# child doesn't work — pydantic-ai spawns + kills the child per request.
# See python-mcp-server commit 1fbe75a + #63.
CMD ["sh", "-c", "uv run -m python_mcp_server seed && uv run -m src.main"]
