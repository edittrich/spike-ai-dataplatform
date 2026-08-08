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

`tests/` is a real pytest suite led by negative security tests (see Q9 in the hardening plan's history): it asserts every previously-verified guardrail bypass (Cypher `SET`/`REMOVE`/`MERGE`/`CALL`, SQL `pg_read_file`/`COPY ... TO PROGRAM`/stacked statements) is rejected, that `BearerAuthMiddleware` fail-closed behavior holds (401 on missing/wrong/non-ASCII token, 200 on the correct one), and that `contracts/*.yaml` has no column/`allowed_values` drift against the live migration SQL. Two of its files (`test_postgres_readonly_role.py`, `test_schema_dbml_drift.py`) additionally run live checks against the `mcp_readonly` role / the DB-introspected schema when a database is reachable, and skip cleanly (not fail) when it isn't — e.g. in CI, which has no Postgres service. Pipeline scripts themselves still verify by running directly — most end in `if __name__ == "__main__": main()` and print a pass/fail summary to stdout rather than using an assert-based framework. These are the exact steps CI (`.github/workflows/ci.yml`) runs on every push/PR to `main`:

```bash
python3 -m py_compile scripts/*.py mcp_server/*.py                    # syntax check
python3 -m ruff check --select E9,F821,F822,F823 scripts mcp_server   # undefined-name/syntax lint (blocking)
python3 -m ruff check --select F scripts mcp_server                   # broader style lint (informational only)
python3 -m pip_audit -r requirements.txt                              # dependency CVE scan (informational only)
python3 -m pytest tests/ -v                             # negative security tests, auth middleware tests, contract/schema drift check
python3 scripts/ai_safety_guardrails.py                 # PII redaction / prompt-injection / read-only-query self-test
python3 scripts/llmops_telemetry.py                     # telemetry tracing self-test
python3 -m mcp_server.test_mcp_server                    # asserts registration of all 6 MCP tools + 2 resources, and
                                                          # exercises all 6 tools' execution handlers (including
                                                          # hybrid_rag_search, which degrades to a clean error string
                                                          # rather than raising when no embedding model is installed,
                                                          # so it's safe to call even without the full stack), so it
                                                          # can actually fail
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
python3 scripts/build_knowledge_graph.py --yes                # load PostgreSQL data into Neo4j (--yes confirms the graph wipe non-interactively)
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
5. **Agentic protocol** — `mcp_server/financial_data_mcp_server.py` is a FastMCP server exposing 6 tools (`search_data_catalog`, `query_semantic_metrics`, `query_knowledge_graph`, `query_financial_database`, `check_data_quality`, `hybrid_rag_search`), runnable over stdio or as the `mcp_sidecar` SSE container (`:8001/sse`, `MCP_TRANSPORT=sse`). `scripts/ollama_agentic_tool_runner.py` drives these tools autonomously via a local Ollama model. Both this file and `scripts/hybrid_rag_retriever.py` reach Postgres/Neo4j via native drivers (`psycopg2`, `neo4j`), not `docker exec` — the `mcp_sidecar` container has neither the `docker` CLI nor a mounted `docker.sock`, so a `docker exec`-based approach fails there specifically even though it works fine when the same code runs directly on the host. The standalone pipeline scripts in `scripts/` are meant to be run on the host; most still use `docker exec` for read-only queries, which is fine there — but any script that *writes* has been migrated to a native driver instead (`generate_vector_embeddings.py`'s INSERT, `build_knowledge_graph.py`'s and `sync_end_to_end_lineage.py`'s Cypher), both to close the `docker.sock` exposure and because `docker exec`'s shelled-out-string-building was the shape of the C6 injection findings; see `scripts/_neo4j_conn.py`.
6. **Consumption & observability** — Streamlit dashboard (`scripts/rag_explorer_dashboard.py`, `:8501`); Grafana (`:3000`) + Prometheus (`:9090`) scraping real metrics served directly by `mcp_sidecar` (`:8000/metrics`, via `prometheus_client.start_http_server()` in `mcp_server/financial_data_mcp_server.py`'s `main()`) — there is no separate telemetry exporter container; metrics live in the same process that executes tool calls, since Prometheus client objects don't share state across processes. Cross-cutting: `scripts/ai_safety_guardrails.py` (PII redaction, prompt-injection defense, read-only query enforcement) and `scripts/llmops_telemetry.py` (per-tier latency tracing feeding both the process-global Prometheus metrics and a per-call JSON trace view), used by the retrieval/agentic layers above.

### Data domains

Three BIAN/FIBO-aligned domains, each with its own OpenMetadata data product and ODCS contract under `contracts/`: `Party_Customer_Domain`, `Deposit_Liquidity_Domain`, `Loan_Credit_Risk_Domain`. Table and cube names are strictly prefixed by domain (`party_*`, `deposit_*`, `loan_*`, `ref_*`). The full relational schema is documented in `schema.dbml`; tables follow Inmon 3NF with SCD Type 2 temporal headers.

`financial`/`ref` are not exposed through Supabase's PostgREST API (removed from `supabase/config.toml`'s `[api].schemas` — nothing in the platform uses that surface) and have Row-Level Security enabled with no policies for the `anon`/`authenticated` Supabase roles, so neither can read a row even if a schema were re-added there by mistake. Application code reaches Postgres over the wire protocol on `[db].port` (`:54322`) directly, either as the `postgres` superuser (pipeline scripts, Cube.js) or as the least-privilege `mcp_readonly` role (MCP server, hybrid RAG retriever — see above).

### Docker networking

`docker-compose.yml` runs most services with `network_mode: "host"` (Neo4j, Cube.js, Prometheus, Grafana, MCP sidecar) — only the OpenMetadata trio (MySQL, OpenSearch, server) uses bridge networking with published ports. Host-mode services reach each other over `127.0.0.1`, not Docker DNS names; keep this in mind when adding a service or debugging connectivity. Migrating the five host-mode services onto bridge networking was assessed and deliberately deferred (see the comment block at the top of `docker-compose.yml`) — it needs `host.docker.internal`/`extra_hosts` to reach the host-run Postgres, plus consistent updates to `catalog/prometheus.yml`'s scrape targets and every `catalog/grafana/provisioning/datasources/*.yml` URL, not a one-line toggle.

MySQL (`33060`), OpenSearch (`9200`), and `openmetadata_server` (`8585`, via `OPENMETADATA_HOST`, default `127.0.0.1`) all publish to `127.0.0.1` only, not `0.0.0.0` — reachable from the host for local debugging/UI access, but not from the network (OpenSearch in particular runs with `DISABLE_SECURITY_PLUGIN=true`, so it must never be exposed beyond localhost; same `MCP_HOST`-style configurable-but-secure-by-default pattern as `OPENMETADATA_HOST`, in case LAN access to the catalog UI is deliberately wanted). All services declare a `healthcheck:`; `openmetadata_server` waits on `openmetadata_db`/`openmetadata_search`, and `mcp_sidecar`/`grafana` wait on their own compose-internal dependencies (`neo4j`+`cube`, `prometheus` respectively), all via `condition: service_healthy`. Every service also sets `security_opt: no-new-privileges:true` and a bounded `logging:` driver (10MB × 3 files); config bind mounts (Cube.js's model/`cube.js`, Prometheus's config, Grafana's provisioning) are `:ro`; Prometheus and Grafana persist to named volumes (`prometheus_data`/`grafana_data`) rather than losing all history on every container recreate.

### Secrets convention

All credentials (JWT tokens, DB passwords, API secrets) must come from `os.getenv(...)` with an empty-string default — never hardcode a fallback value, even as the `os.getenv` default. (This exact mistake previously shipped a live, non-expiring OpenMetadata bot JWT hardcoded into 8 files, and later recurred as a hardcoded `password12345` Neo4j fallback and a hardcoded MySQL default in `docker-compose.yml` — both since removed.) Real values live only in `.env` (gitignored); `.env.example` holds placeholders.

The MCP SSE endpoint (`mcp_sidecar`, `:8001`) and the Cube.js semantic layer (`:4000`) both enforce real authentication now — `MCP_API_KEY` (bearer token, checked by `BearerAuthMiddleware` in `mcp_server/financial_data_mcp_server.py`) and `CUBEJS_API_SECRET` (bearer token, checked by `cube/cube.js`'s `checkAuth`, in both `CUBEJS_DEV_MODE` settings) respectively. Neither has a hardcoded fallback; in SSE mode an unset `MCP_API_KEY` makes the server refuse to start at all (fail closed, not open), and an unset `CUBEJS_API_SECRET` makes Cube.js reject every request. The MCP server and `scripts/hybrid_rag_retriever.py` also connect to Postgres as a dedicated non-superuser role (`mcp_readonly`, `MCP_PG_READONLY_USER`/`PASSWORD`) rather than the `postgres` superuser used elsewhere in the pipeline — see `supabase/migrations/20260807151500_create_mcp_readonly_role.sql`.

Beware: `openmetadata_server` reads its DB password from the env var `DB_USER_PASSWORD`, not `DB_PASSWORD` — the image's own config template silently falls back to a hardcoded default password if the wrong var name is set. `docker-compose.yml` sets the correct name; if you ever see `Access denied for user 'openmetadata_user'` despite a verified-correct password, check that first.

Beware also: the shared connection-helper modules (`scripts/_neo4j_conn.py`, `scripts/_openmetadata_client.py`, `scripts/_embedding_backend.py`) read their env config at *import time*, not lazily — so each must be imported *after* `scripts._dotenv_boot.load_env()` has run in the importing script, or it silently captures empty credentials. This bit twice during Phase 3's development (a `Neo.ClientError.Security.Unauthorized` from `_neo4j_conn` being imported too early) before the fix; every affected file now has an explicit comment at the import site.

### Further reading

- `docs/ARCHITECTURE.md` — high-level architecture, data model design, BIAN/FIBO domain alignment, and roadmap.
- `docs/APPLICATION_RUNBOOK.md` — full service inventory, script-by-script deep dive, troubleshooting guide, known issues.
