FROM python:3.14-slim
WORKDIR /app
# postgresql-client: mcp's `seed` shells out to psql for the pgvector dump.
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
COPY packages packages/
RUN pip install uv && uv sync --frozen --no-dev
RUN find packages -name "test_*.py" -delete
WORKDIR /app/packages/server
# Seed-then-serve: mcp seed runs to completion (vector + graph) BEFORE
# uvicorn starts. Background-seed inside the MCP child doesn't work —
# pydantic-ai spawns + kills the child per request.
CMD ["sh", "-c", "uv run -m ems_analyst_mcp seed && uv run -m src.main"]
