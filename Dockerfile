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
CMD ["uv", "run", "-m", "src.main"]
