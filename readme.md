# EMS Analyst Server 🛰️

![](https://img.shields.io/gitlab/pipeline-status/arcnode-io/ems-analyst-server?branch=main&logo=gitlab)
![](https://gitlab.com/arcnode-io/ems-analyst-server/badges/main/coverage.svg)
![](https://img.shields.io/badge/fastapi-gray?logo=fastapi)
![](https://img.shields.io/badge/pydantic-gray?logo=pydantic)
![](https://img.shields.io/badge/timescaledb-gray?logo=timescale)
![](https://img.shields.io/badge/mlflow-gray?logo=mlflow)

> The running FastAPI process that composes [`analyst-model`](https://gitlab.com/arcnode-io/ems-analyst-model) and [`analyst-agent`](https://gitlab.com/arcnode-io/ems-analyst-agent) behind a single HTTP interface

## Architecture


## API Endpoints

### Historical Data

```plantuml
participant client
participant server
database timescaledb

client -> server: GET /historical?start=2024-01-01&end=2024-12-31&metrics=solar_mw
server -> timescaledb: SELECT * FROM solar_generation WHERE timestamp BETWEEN...
timescaledb -> server: historical data
server -> client: JSON response with timeseries data
```

### Predictions

```plantuml
participant client
participant server
database mlflow

client -> server: POST /predictions {"horizon": "24h", "features": {...}}
server -> mlflow: load latest solar forecast model
mlflow -> server: model artifacts
server -> server: generate predictions
server -> client: JSON response with forecast data
```

### Chat Completions

```plantuml
participant client
participant server
participant agent

client -> server: POST /chat {"message": "What's the solar forecast?", "session_id": "123"}
server -> agent: chat_completion(message, session_id)
agent -> agent: RAG + knowledge graph + external APIs
agent -> server: AI response
server -> client: JSON response with chat completion
```

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
