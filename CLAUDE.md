# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Enterprise AI-Enabled Data Platform (PoC): a BIAN/FIBO-aligned financial data platform combining a 3NF PostgreSQL core (Supabase + pgvector), a Cube.js semantic layer, a Neo4j knowledge graph, an OpenMetadata catalog, and a FastMCP server that exposes the whole stack as tools to AI agents. There is no application build step — the platform is a set of standalone Python scripts and Docker services wired together at runtime via `.env`.

## Commands

### Environment setup

```bash
cp .env.example .env   # then fill in POSTGRES_PASSWORD, OPENMETADATA_JWT_TOKEN, OPENMETADATA_MYSQL_PASSWORD,
                        # CUBEJS_API_SECRET, NEO4J_PASSWORD, GRAFANA_ADMIN_PASSWORD, MCP_API_KEY,
                        # MCP_PG_READONLY_PASSWORD
```

`OPENMETADATA_MYSQL_PASSWORD` and `MCP_API_KEY` have no fallback default — leaving either unset breaks `openmetadata_server` (MySQL auth failure) or, in SSE mode, makes the MCP server refuse to start at all (it fails closed rather than falling back to unauthenticated), respectively. See `docker-compose.yml`'s comments on `DB_USER_PASSWORD` and `mcp_server/financial_data_mcp_server.py`'s `BearerAuthMiddleware` for why. `MCP_PG_READONLY_PASSWORD` also has no fallback — the MCP server and `scripts/hybrid_rag_retriever.py` connect to Postgres as the least-privilege `mcp_readonly` role (not the superuser), whose password isn't set by its migration and must be applied once via `python3 scripts/configure_readonly_role.py`.

### Start/stop the stack

PostgreSQL is **not** a `docker-compose.yml` service — it's managed separately by the Supabase CLI and must be started first:

```bash
npm run supabase:start     # starts Postgres, applies migrations (first run only; use supabase:db:reset to re-seed)
docker compose up -d       # everything else: OpenMetadata, Neo4j, Cube.js, Prometheus, Grafana, MCP sidecar
docker compose ps
docker compose logs -f <service>
docker compose restart <service>
```

`scripts/bootstrap_platform.sh` runs the full sequence below (this plus the data pipeline) in one command from an empty checkout.

`package.json`'s `cube:*`, `neo4j:*`, and `catalog:*` npm scripts point at `cube/docker-compose.yml`, `neo4j/docker-compose.yml`, and `catalog/docker-compose.yml` — those per-service compose files were consolidated into the root `docker-compose.yml` and currently don't exist on disk. Use the plain `docker compose` commands above instead of those npm scripts.

### Syntax check / verification

There is no pytest suite despite `pytest` being in `requirements.txt`. Verification is done by running pipeline scripts directly — most end in `if __name__ == "__main__": main()` and print a pass/fail summary to stdout rather than using an assert-based framework. These are the exact steps CI (`.github/workflows/ci.yml`) runs on every push/PR to `main`:

```bash
python3 -m py_compile scripts/*.py mcp_server/*.py                    # syntax check
python3 -m ruff check --select E9,F821,F822,F823 scripts mcp_server   # undefined-name/syntax lint (blocking)
python3 -m ruff check --select F scripts mcp_server                   # broader style lint (informational only)
python3 -m pip_audit -r requirements.txt                              # dependency CVE scan (informational only)
python3 scripts/ai_safety_guardrails.py               # PII redaction / prompt-injection / read-only-query self-test
python3 scripts/llmops_telemetry.py                    # telemetry tracing self-test
python3 -m mcp_server.test_mcp_server                  # asserts registration of all 6 MCP tools + 2 resources, and
                                                         # exercises 5 of the 6 tools' execution handlers (all but
                                                         # hybrid_rag_search), so it can actually fail
```

Additional (not in CI, need the full stack + data loaded):

```bash
python3 scripts/evaluate_agentic_retrieval.py   # 5-scenario benchmark + RAG Triad scorecard
```

### Full data pipeline

Run in this order against a running stack to go from empty databases to a queryable platform.
`scripts/generate_synthetic_data.py` only *writes* `supabase/seed.sql` — it does not load it — and
`scripts/populate_openmetadata_tables.py` is a real dependency of four later steps (they fetch table
entities from the catalog and silently no-op if it hasn't run), not an optional extra:

```bash
python3 scripts/generate_synthetic_data.py                    # writes supabase/seed.sql (does not load it)
npm run supabase:db:reset                                      # applies migrations + loads the seed above
python3 scripts/configure_readonly_role.py                     # sets the mcp_readonly role's password (idempotent)
python3 scripts/build_knowledge_graph.py                      # load PostgreSQL data into Neo4j
python3 scripts/populate_openmetadata_tables.py                # register tables -- required before the 4 lines below
python3 scripts/automate_openmetadata_pii_and_profiling.py    # PII tagging + profiling
python3 scripts/ground_fibo_ontology_uris.py                  # link catalog entities to W3C FIBO URIs
python3 scripts/register_openmetadata_data_contracts.py       # publish domains + ODCS-style contracts from contracts/
python3 scripts/execute_openmetadata_data_quality_tests.py    # register + run data quality assertions
python3 scripts/sync_end_to_end_lineage.py                    # PostgreSQL -> Cube.js -> Neo4j lineage DAGs
python3 scripts/generate_vector_embeddings.py                 # embed + index into pgvector (HNSW) -- genuinely last
```

The four PII/FIBO/contracts/quality-test lines are mutually independent (each depends only on
`populate_openmetadata_tables.py`, not on each other) and can run in parallel if pipeline runtime
matters. `scripts/bootstrap_platform.sh` runs this entire sequence, plus starting Postgres and Docker
Compose, in one command.

Then `scripts/hybrid_rag_retriever.py`, `scripts/ollama_agentic_tool_runner.py`, and `streamlit run scripts/rag_explorer_dashboard.py` operate against the fully-loaded stack.

## Architecture

### Layered stack (bottom to top)

1. **Ingestion** — `scripts/generate_synthetic_data.py` seeds BIAN/FIBO records into PostgreSQL `ref`/`financial` schemas defined by the Supabase migrations in `supabase/migrations/`.
2. **Storage** — Supabase PostgreSQL+pgvector (`:54322`), Neo4j 5 (`:7687`), MySQL (OpenMetadata's backend DB).
3. **Semantic & governance** — Cube.js cubes in `cube/model/cubes/*.yml` (`:4000`); OpenMetadata catalog (`:8585`) with domains/contracts under `contracts/*.yaml`; W3C FIBO ontology grounding (`ontology/*.ttl`).
4. **Retrieval** — `scripts/hybrid_rag_retriever.py` is the orchestrator: it fuses pgvector HNSW vector search, `scripts/neural_reranker.py` cross-encoder re-ranking, `scripts/text_to_cypher_builder.py` NL→Cypher compilation, Cube.js metrics, and raw SQL into a single "4-tier hybrid RAG" call.
5. **Agentic protocol** — `mcp_server/financial_data_mcp_server.py` is a FastMCP server exposing 6 tools (`search_data_catalog`, `query_semantic_metrics`, `query_knowledge_graph`, `query_financial_database`, `check_data_quality`, `hybrid_rag_search`), runnable over stdio or as the `mcp_sidecar` SSE container (`:8001/sse`, `MCP_TRANSPORT=sse`). `scripts/ollama_agentic_tool_runner.py` drives these tools autonomously via a local Ollama model. Both this file and `scripts/hybrid_rag_retriever.py` reach Postgres/Neo4j via native drivers (`psycopg2`, `neo4j`), not `docker exec` — the `mcp_sidecar` container has neither the `docker` CLI nor a mounted `docker.sock`, so a `docker exec`-based approach fails there specifically even though it works fine when the same code runs directly on the host. (The other, standalone pipeline scripts in `scripts/` are meant to be run on the host and still use `docker exec`, which is fine there.)
6. **Consumption & observability** — Streamlit dashboard (`scripts/rag_explorer_dashboard.py`, `:8501`); Grafana (`:3000`) + Prometheus (`:9090`) scraping real metrics served directly by `mcp_sidecar` (`:8000/metrics`, via `prometheus_client.start_http_server()` in `mcp_server/financial_data_mcp_server.py`'s `main()`) — there is no separate telemetry exporter container; metrics live in the same process that executes tool calls, since Prometheus client objects don't share state across processes. Cross-cutting: `scripts/ai_safety_guardrails.py` (PII redaction, prompt-injection defense, read-only query enforcement) and `scripts/llmops_telemetry.py` (per-tier latency tracing feeding both the process-global Prometheus metrics and a per-call JSON trace view), used by the retrieval/agentic layers above.

### Data domains

Three BIAN/FIBO-aligned domains, each with its own OpenMetadata data product and ODCS contract under `contracts/`: `Party_Customer_Domain`, `Deposit_Liquidity_Domain`, `Loan_Credit_Risk_Domain`. Table and cube names are strictly prefixed by domain (`party_*`, `deposit_*`, `loan_*`, `ref_*`). The full relational schema is documented in `schema.dbml`; tables follow Inmon 3NF with SCD Type 2 temporal headers.

`financial`/`ref` are not exposed through Supabase's PostgREST API (removed from `supabase/config.toml`'s `[api].schemas` — nothing in the platform uses that surface) and have Row-Level Security enabled with no policies for the `anon`/`authenticated` Supabase roles, so neither can read a row even if a schema were re-added there by mistake. Application code reaches Postgres over the wire protocol on `[db].port` (`:54322`) directly, either as the `postgres` superuser (pipeline scripts, Cube.js) or as the least-privilege `mcp_readonly` role (MCP server, hybrid RAG retriever — see above).

### Docker networking

`docker-compose.yml` runs most services with `network_mode: "host"` (Neo4j, Cube.js, Prometheus, Grafana, MCP sidecar) — only the OpenMetadata trio (MySQL, OpenSearch, server) uses bridge networking with published ports. Host-mode services reach each other over `127.0.0.1`, not Docker DNS names; keep this in mind when adding a service or debugging connectivity. MySQL (`33060`) and OpenSearch (`9200`) publish to `127.0.0.1` only, not `0.0.0.0` — both are reachable from the host for local debugging, but not from the network (OpenSearch in particular runs with `DISABLE_SECURITY_PLUGIN=true`, so it must never be exposed beyond localhost). All services declare a `healthcheck:`; `openmetadata_server` waits on `openmetadata_db`/`openmetadata_search` reaching `condition: service_healthy` before starting.

### Secrets convention

All credentials (JWT tokens, DB passwords, API secrets) must come from `os.getenv(...)` with an empty-string default — never hardcode a fallback value, even as the `os.getenv` default. (This exact mistake previously shipped a live, non-expiring OpenMetadata bot JWT hardcoded into 8 files, and later recurred as a hardcoded `password12345` Neo4j fallback and a hardcoded MySQL default in `docker-compose.yml` — both since removed.) Real values live only in `.env` (gitignored); `.env.example` holds placeholders.

The MCP SSE endpoint (`mcp_sidecar`, `:8001`) and the Cube.js semantic layer (`:4000`) both enforce real authentication now — `MCP_API_KEY` (bearer token, checked by `BearerAuthMiddleware` in `mcp_server/financial_data_mcp_server.py`) and `CUBEJS_API_SECRET` (bearer token, checked by `cube/cube.js`'s `checkAuth`, in both `CUBEJS_DEV_MODE` settings) respectively. Neither has a hardcoded fallback; in SSE mode an unset `MCP_API_KEY` makes the server refuse to start at all (fail closed, not open), and an unset `CUBEJS_API_SECRET` makes Cube.js reject every request. The MCP server and `scripts/hybrid_rag_retriever.py` also connect to Postgres as a dedicated non-superuser role (`mcp_readonly`, `MCP_PG_READONLY_USER`/`PASSWORD`) rather than the `postgres` superuser used elsewhere in the pipeline — see `supabase/migrations/20260807151500_create_mcp_readonly_role.sql`.

Beware: `openmetadata_server` reads its DB password from the env var `DB_USER_PASSWORD`, not `DB_PASSWORD` — the image's own config template silently falls back to a hardcoded default password if the wrong var name is set. `docker-compose.yml` sets the correct name; if you ever see `Access denied for user 'openmetadata_user'` despite a verified-correct password, check that first.

### Further reading

- `docs/ARCHITECTURE.md` — high-level architecture, data model design, BIAN/FIBO domain alignment, and roadmap.
- `docs/APPLICATION_RUNBOOK.md` — full service inventory, script-by-script deep dive, troubleshooting guide, known issues.
