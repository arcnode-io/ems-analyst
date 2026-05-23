# ems-analyst

Monorepo for the arcnode EMS analyst stack — a uv workspace of three packages:

| package | role |
|---|---|
| [`packages/mcp/`](packages/mcp/) | `ems-analyst-mcp` — domain knowledge MCP server (Graphiti graph + pgvector RAG) |
| [`packages/agent/`](packages/agent/) | `ems-analyst-agent` — pydantic-ai agent: tools, prompts, MCP client |
| [`packages/server/`](packages/server/) | `ems-analyst-server` — FastAPI surface: `/analyst/chat` (SSE), `/forecast`, `/measurements`, `/description` |

`server` embeds `agent` in-process; `agent` spawns `mcp` as a stdio MCP toolset. Workspace-internal deps are wired at the root `[tool.uv.sources]` — no git URLs, no per-repo lock thrash.

## Layout

```
ems-analyst/
├── pyproject.toml        # uv workspace root
├── uv.lock               # single lock for all 3
├── Dockerfile            # builds the server image (bundles agent + mcp)
└── packages/
    ├── mcp/      (pyproject, src/ems_analyst_mcp, tests)
    ├── agent/    (pyproject, src/ems_analyst_agent, tests)
    └── server/   (pyproject, src, tests, cfg.yml)
```

## Workflows

```bash
uv sync --dev                                   # install all 3 + dev deps
uv run --package ems-analyst-mcp pytest         # test one package
uv run --package ems-analyst-server poe checks  # lint/audit one package
uv run --directory packages/server -m src.main  # run server locally
```

## Build

```bash
docker build -t ems-analyst-server .            # production image (server CMD)
```

## History

Each `packages/<name>/` retains its original repo history via `git subtree`. Previous standalone repos (`arcnode-io/ems-analyst-{mcp,agent,server}`) are archived in favour of this one.
