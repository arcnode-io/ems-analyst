# Scoped graph validation

Validated 2026-10-12 with the real MCP stdio server, local `gemma4:26b` answers,
`qwen3-embedding:4b` markdown retrieval, isolated Neo4j 5.26 and pgvector/Postgres 16.
The full airgapped vector seed was restored unchanged (3,505 passages).
The actual Neo4j seed restorer loaded 184 corpus nodes and 496 relationships,
plus its existing seed marker. No demo or production graph was modified.

| Artifact | Previous bytes | Scoped bytes | Reduction |
|---|---:|---:|---:|
| Neo4j gzip | 96,183,966 | 89,134 | 99.91% |
| Neptune CSV pair | 124,822,055 | 378,647 | 99.70% |

The graph retains BESS chapter-5 provenance, 256 searchable facts, three
frontmatter-derived standard supersession pairs and the source-attributed
Victorian Big Battery incident chain. Graph vectors and communities are absent;
search uses lexical seeds and bounded traversal. Markdown/vector seeds are unchanged.
All golden cases are tagged by query shape.

The [agent report](agent-report.md) passes all nine cases for answer concepts,
matching returned tool evidence, and routing (four flat, three supersession,
two multi-hop). An initial hierarchy run used only RAG; an explicit graph-routing
instruction corrected it, and both multi-hop cases were rerun successfully.
The seven previously passing cases were retained via the evaluator resume option.
The regex gates check selected concepts; they are not a general accuracy guarantee.

The [retrieval report](retrieval-report.md) has complete required link evidence in
the top ten for all five graph cases. Flat lookup Recall@5 is 14/15 (93%), MRR
0.699. The unchanged Borduria/Syldavia passage ranks eighth, as in the initial
full-markdown run. Graph Recall@5 is 5/5, MRR 0.900. Negative examples are reported,
but no calibrated abstention threshold is claimed.

Unit validation: 42 MCP/agent scoring/report tests and six seed tests pass.
Run MCP units with `PYTHONPATH=packages/mcp` for existing `src` namespace mocks.
Changed seed scripts pass Ruff, Black and type checks. Neptune CSV endpoints,
relationship equivalence, scalar edge properties and provenance were checked;
no live Neptune/AOSS cluster was loaded.

The [manifest](manifest.json) records reproducible artifact checksums. New S3
keys are `seed/graph-neo4j-scoped-v1.cypher.gz`, its matching `-e2e` artifact,
`seed/graph-neptune-scoped-v1/{vertices,edges}.csv` and
`seed/graph-scoped-v1-manifest.json` in `arcnode-public`. Existing large keys
remain available for rollback. Defaults select the new artifacts on fresh installs;
existing seed markers are unchanged.

Reproduce using the seed repository's `src/compact_graph.py` and README, then
`python -m ems_analyst_mcp.eval_retrieval --graph` and
`python -m ems_analyst_agent.eval_domain --model gemma4:26b --output /tmp/scoped-eval`.
Supply `GRAPH_URL`, `VECTOR_URL`, `ENV=local`, and a customer config with the
Neo4j backend and matching local Ollama embedding provider.
