# ems-analyst 📊🤖

![](https://img.shields.io/badge/3.13-gray?logo=python)
![](https://img.shields.io/badge/uv-gray?logo=uv)

> Monorepo for the arcnode EMS analyst stack — a uv workspace of three packages: the domain knowledge MCP server, the pydantic-ai analyst agent, and the FastAPI surface that fronts both.

## Packages

| | role |
|---|---|
| [`packages/mcp/`](packages/mcp/) | `ems-analyst-mcp` — domain knowledge MCP server: Graphiti graph + pgvector RAG over the curated energy corpus (BESS, NERC-CIP, power economics, protocols). |
| [`packages/agent/`](packages/agent/) | `ems-analyst-agent` — pydantic-ai agent: tools, prompts, telemetry/forecast tool routing, MCP client. |
| [`packages/server/`](packages/server/) | `ems-analyst-server` — FastAPI surface: `/measurements`, `/forecast`, `/description`, `/analyst/chat` (SSE). Embeds the agent in-process. |

Sibling repo (separate by design — ML batch, different stack, ml-engineer's): [`ems-analyst-model`](https://gitlab.com/arcnode-io/ems-analyst-model) — nightly ETL (gridstatus) → train (Prophet / XGBoost / LightGBM) → MLflow → score → write `forecasts` table the server reads.

## Architecture

```plantuml
rectangle ems_analyst <<monorepo>> {
  rectangle mcp
  rectangle agent
  rectangle server
}
rectangle ems_analyst_model

database timeseries <<postgres+timescaledb>>
database knowledge_vector <<pgvector>>
database knowledge_graph <<neo4j>>

cloud ercot <<gridstatus.io>>
cloud llm <<ollama / bedrock>>
cloud weather_news <<openweathermap / rss>>

rectangle ems_hmi

agent -u-> mcp                : MCP stdio
mcp -u-> knowledge_vector     : SQL
mcp -u-> knowledge_graph      : Cypher
agent -u-> llm                : HTTP
agent -u-> weather_news       : HTTP
agent -d-> server             : HTTP (telemetry, forecast)
server -d-> timeseries        : SQL

ems_analyst_model -u-> timeseries : SQL (write forecasts)
ems_analyst_model -l-> ercot       : HTTP

ems_hmi -u-> server           : HTTP / SSE
```

## Server endpoints

| route | purpose | data source |
|---|---|---|
| `GET /health` | liveness | — |
| `GET /description` | measurement inventory (device + name + sample count) | `timeseries.measurements` (or CSV mock when `ENV=demo`) |
| `GET /measurements` | hourly-bucketed timeseries | same |
| `GET /forecast` | published forecast curve | `timeseries.forecasts` (written by `ems-analyst-model`) |
| `POST /analyst/chat` | agent chat — content-negotiated SSE on `Accept: text/event-stream` | agent → tools → mcp/server |

## Data flow

```plantuml
participant ems_hmi
participant server
participant agent
participant mcp
database timeseries

ems_hmi -> server : GET /measurements
server -> timeseries : SQL
timeseries -> server : rows
server -> ems_hmi : timeseries

ems_hmi -> server : GET /forecast
server -> timeseries : SQL (forecasts)
timeseries -> server : rows
server -> ems_hmi : forecast curve

ems_hmi -> server : POST /analyst/chat
server -> agent : run_turn_stream
agent -> mcp : MCP tool calls (graph + RAG)
agent -> server : tool calls (/measurements, /forecast, /description)
agent -> server : token stream
server -> ems_hmi : SSE
```

## Layout

```
ems-analyst/
├── pyproject.toml        # uv workspace root
├── uv.lock               # single lock for all 3 packages
├── Dockerfile            # builds the server image (bundles agent + mcp)
├── .gitlab-ci.yml        # per-package poe checks + pytest + coverage
└── packages/
    ├── mcp/      (pyproject, src/ems_analyst_mcp, tests)
    ├── agent/    (pyproject, src/ems_analyst_agent, tests)
    └── server/   (pyproject, src, tests, cfg.yml)
```

## Workflows

```bash
uv sync --all-packages --dev                                                    # install all 3 + dev deps

# Run one package's checks / tests
(cd packages/server && uv run poe checks)
uv run --package ems-analyst-agent --directory packages/agent pytest
uv run --package ems-analyst-mcp   --directory packages/mcp   pytest

# Run the server locally
(cd packages/server && uv run -m src.main)

# Build the deployable image (server CMD; agent + mcp bundled via workspace)
docker build -t ems-analyst-server .
```

## History

Each `packages/<name>/` retains its original repo history via `git subtree`. The previously standalone repos (`arcnode-io/ems-analyst-{mcp,agent,server}` + the umbrella `ems-analyst-api`) are archived in favour of this monorepo.
