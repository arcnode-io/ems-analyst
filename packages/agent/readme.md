# EMS Analyst Agent 🤖💬

![](https://img.shields.io/gitlab/pipeline-status/arcnode-io/ems-analyst?branch=main&label=checks-agent&logo=gitlab)
![](https://gitlab.com/arcnode-io/ems-analyst/badges/main/coverage.svg?job=checks-agent)
![](https://img.shields.io/badge/ty_checked-gray?logo=astral)
![](https://img.shields.io/badge/llama3-gray?logo=meta)
![](https://img.shields.io/badge/pydantic--ai-gray?logo=pydantic)
![](https://img.shields.io/badge/neo4j-gray?logo=neo4j)
![](https://img.shields.io/badge/postgresql-gray?logo=postgresql)

> Energy analyst agent with persistent memory, agentic RAG using vector DB, Neo4j knowledge graph powered by Graphiti, and external APIs for comprehensive energy market analysis

## Architecture

```plantuml
rectangle agent {
  database vector_chat_history
  rectangle conversational_llm
  rectangle tool_api
}
rectangle domain_mcp_server {
    database vector_knowledge_base
    database knowledge_graph
    rectangle query_logic
}


cloud openweather 
cloud gridstatus_io 
cloud energy_news_rss 
query_logic -u-> knowledge_graph: Cypher
query_logic -u-> vector_knowledge_base: SQL
query_logic -d- tool_api
tool_api -r-> vector_chat_history: SQL
tool_api -d-> openweather: HTTP
tool_api -d-> gridstatus_io: HTTP
tool_api -d-> energy_news_rss: HTTP
conversational_llm -r-> tool_api

```

## Tools

### Memory Tools

- **Conversation History**: Persistent message storage and retrieval

- **Context Awareness**: Access to previous conversations and analysis

- **Session Management**: Multi-turn conversation capabilities

### Vector Search Tools

- **Semantic Search**: Vector similarity search across energy domain documents

- **Hybrid Search**: Combined vector and keyword search

- **Document Retrieval**: Full document access with chunking

### Knowledge Graph Tools

- **Entity Relationships**: Explore connections between energy concepts

- **Timeline Queries**: Historical analysis of energy events

- **Graph Search**: Semantic queries across knowledge relationships

### External API Tools

- **Weather Analysis**: OpenWeather API for weather impact on energy systems

- **Market Data**: YES Energy API for real-time energy market information

- **Geopolitical Intelligence**: Energy News RSS Feeds:Reuters Energy, Bloomberg Energy, OilPrice.com, S&P Global Commodity Insights all publish feeds. Aggregate and done.

## Prompts

### System Prompts

- `system_analyst.md`: Core energy analyst personality and capabilities


### Task Prompts

- `market_analysis.md`: Energy market analysis and forecasting

- `weather_impact.md`: Weather correlation with energy demand/supply

- `geopolitical_analysis.md`: Geopolitical event impact assessment

- `technical_analysis.md`: Power systems and grid analysis

### Response Prompts

- `explanation.md`: Detailed technical explanations

- `summary.md`: Executive summary format

- `recommendation.md`: Actionable recommendations

## Domain MCP Server

### Vector Database & Knowledge Graph Content
- seeded with relavant corpus of text to answer questions energy economics,  industrial protocols, BESS, and datacenter management. As well as regulatory compliance like NERC-CIP


### Knowledge Graph Entities

- **Market Participants**: Utilities, ISOs, traders, generators

- **Infrastructure**: Power plants, transmission lines, storage systems

- **Regulations**: FERC orders, state policies, market rules

- **Events**: Outages, weather events, policy changes

## Project Structure

```
├── pyproject.toml              # Dependencies and build config
├── src/
│   ├── main.py                 # Agent entry point
│   ├── agent.py                # Pydantic AI agent definition
│   ├── agent_test.py           # Agent unit tests
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── history.py          # Message history management
│   │   └── history_test.py
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── vector_search.py    # Vector search implementation
│   │   ├── vector_search_test.py
│   │   ├── graph_utils.py      # Knowledge graph utilities
│   │   └── graph_utils_test.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── weather.py          # OpenWeather API integration
│   │   ├── weather_test.py
│   │   ├── markets.py          # gridtatus.io
│   │   ├── markets_test.py
│   │   ├── geopolitical.py     # Energy News RSS
│   │   └── geopolitical_test.py
│   └── utils/
│       ├── __init__.py
│       ├── embeddings.py       # Embedding utilities
│       └── embeddings_test.py
├── prompts/
│   ├── system/
│   │   ├── system_analyst.md
│   ├── tasks/
│   │   ├── market_analysis.md
│   │   ├── weather_impact.md
│   │   ├── geopolitical_analysis.md
│   │   └── technical_analysis.md
│   └── responses/
│       ├── explanation.md
│       ├── summary.md
│       └── recommendation.md
├── tests/
│   └── test_integration.py     # End-to-end agent tests
└── README.md                   # This file
```
