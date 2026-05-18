# EMS Analyst Server 🛰️

![](https://img.shields.io/gitlab/pipeline-status/arcnode-io/ems-analyst-server?branch=main&logo=gitlab)
![](https://gitlab.com/arcnode-io/ems-analyst-server/badges/main/coverage.svg)
![](https://img.shields.io/badge/ty_checked-gray?logo=astral)
![](https://img.shields.io/badge/fastapi-gray?logo=fastapi)
![](https://img.shields.io/badge/pydantic-gray?logo=pydantic)
![](https://img.shields.io/badge/timescaledb-gray?logo=timescale)
![](https://img.shields.io/badge/mlflow-gray?logo=mlflow)

> The running FastAPI process that composes [`analyst-model`](https://gitlab.com/arcnode-io/ems-analyst-model) and [`analyst-agent`](https://gitlab.com/arcnode-io/ems-analyst-agent) behind a single HTTP interface

## Architecture

**Principle:** the agent is just another client of the server, same as the HMI. Both speak the same REST contracts. Any data path added for the HMI is available to the agent as a tool, and vice versa.

## API Endpoints

### GET `/sites/{site_id}/measurements`

Hourly-bucketed gap-filled timeseries from the canonical `measurements` table.

Params: `device_id` (str), `measurement` (str), `start` (ISO-8601), `end` (ISO-8601), `aggregation` (mean|max|min|last, default `mean`).
Response: `{ site_id, device_id, measurement, unit, points: [{ ts, value|null }] }`.

### GET `/sites/{site_id}/devices`

Distinct devices at the site with their latest `status` measurement.

Params: `status` (repeatable; optional filter).
Response: `{ site_id, devices: [{ device_id, status|null }] }`.

### GET `/sites/{site_id}/description`

Inventory of distinct `(device, measurement)` pairs + sample counts. Discovery payload — agents call this before guessing measurement names.

Response: `{ site_id, pairs: [{ device_id, measurement, samples }] }`.

### GET `/sites/{site_id}/forecast`

Query the `forecasts` table (populated by `ems-analyst-model`'s scoring step).

Params: `measurement` (str), `start` (ISO-8601), `end` (ISO-8601).
Response: `{ site_id, measurement, unit, model_name, model_version, points: [{ forecast_for, value }] }`.

### POST `/analyst/chat`

Multi-turn analyst chat. Delegates to `ems_analyst_agent.Agent.chat_turn`; persists thread in Postgres. See HMI handoff for body shape.

## Project Structure
```
├── pyproject.toml              # Dependencies and build config
├── src/
│   ├── main.py                 # FastAPI application entry point
│   ├── app.py                  # Application factory and configuration
│   ├── models.py               # Pydantic request/response models
│   ├── database.py             # Database connections
│   ├── historical/
│   │   ├── historical_controller.py    # Historical data endpoints
│   │   └── historical_service.py       # TimescaleDB service
│   ├── predictions/
│   │   └── predictions_controller.py   # Prediction endpoints (MLflow integration)
│   └── chat/
│       └── chat_controller.py          # Chat completion endpoints (agent integration)
├── tests/
│   └── test_integration.py     # FastAPI TestClient integration tests
└── README.md                   # This file
````

## Configuration

### Environment Variables

- `TIMESCALEDB_URL`: TimescaleDB connection string

- `MLFLOW_TRACKING_URI`: MLflow server URL

- `AGENT_CONFIG`: Agent package configuration

### Dependencies

- **energy-analyst-agent**: Installed as Python package for chat completions

- **FastAPI**: Web framework with automatic OpenAPI documentation

- **TimescaleDB**: Time-series database for historical data

- **MLflow**: Model registry and serving
