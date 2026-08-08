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

Also run once per checkout, before your first commit:

```bash
pip install pre-commit
pre-commit install
```

This installs a local git hook (`.pre-commit-config.yaml` -> `scripts/git-hooks/gitleaks-pre-commit.sh`) that runs `gitleaks protect --staged` via Docker on every `git commit`, blocking it if a likely secret is found in the staged diff — this is C7's originally-deferred "pre-commit hook" half of "add gitleaks or detect-secrets as a pre-commit hook and a CI job"; the CI half already runs as an informational full-history scan in `.github/workflows/ci.yml`. No local `gitleaks` binary or Go toolchain needed, only Docker (which the platform already requires).

### Start/stop the stack

PostgreSQL is **not** a `docker-compose.yml` service — it's managed separately by the Supabase CLI and must be started first:

```bash
npm run supabase:start     # starts Postgres, applies migrations (first run only; use supabase:db:reset to re-seed)
docker compose up -d       # everything else: OpenMetadata, Neo4j, Cube.js, Prometheus, Grafana, Alertmanager,
                            # node/postgres/mysqld exporters, cAdvisor, MCP sidecar
docker compose ps
docker compose logs -f <service>
docker compose restart <service>
```

`scripts/bootstrap_platform.sh` runs the full sequence below (this plus the data pipeline) in one command from an empty checkout.

`package.json` used to have `cube:*`, `neo4j:*`, and `catalog:*` npm scripts pointing at `cube/docker-compose.yml`, `neo4j/docker-compose.yml`, and `catalog/docker-compose.yml` — those per-service compose files were consolidated into the root `docker-compose.yml` a while ago and never existed again on disk, so all 9 scripts had been broken since (Q12/Q14). Removed rather than fixed: their functionality is exactly the plain `docker compose` commands above, so re-pointing them at the root compose file would just be a longer way to type the same thing. Use the plain `docker compose` commands above.

### Syntax check / verification

`tests/` is a real pytest suite led by negative security tests (see Q9 in the hardening plan's history): it asserts every previously-verified guardrail bypass (Cypher `SET`/`REMOVE`/`MERGE`/`CALL`, SQL `pg_read_file`/`COPY ... TO PROGRAM`/stacked statements) is rejected, that `BearerAuthMiddleware` fail-closed behavior holds (401 on missing/wrong/non-ASCII token, 200 on the correct one), and that `contracts/*.yaml` has no column/`allowed_values` drift against the live migration SQL. Two of its files (`test_postgres_readonly_role.py`, `test_schema_dbml_drift.py`) additionally run live checks against the `mcp_readonly` role / the DB-introspected schema when a database is reachable, and skip cleanly (not fail) when it isn't — e.g. in CI, which has no Postgres service. Pipeline scripts themselves still verify by running directly — most end in `if __name__ == "__main__": main()` and print a pass/fail summary to stdout rather than using an assert-based framework. These are the exact steps CI (`.github/workflows/ci.yml`) runs on every push/PR to `main`:

```bash
python3 -m py_compile scripts/*.py mcp_server/*.py                    # syntax check
python3 -m ruff check --select E9,F821,F822,F823 scripts mcp_server   # undefined-name/syntax lint (blocking)
python3 -m ruff check --select F scripts mcp_server                   # broader style lint (informational only)
python3 -m pip_audit -r requirements.txt                              # dependency CVE scan (informational only)
python3 -m bandit -r scripts mcp_server -ll                           # Python security static analysis (informational only) --
                                                                        # the local-OSS equivalent to CodeQL used here instead (Q14):
                                                                        # CodeQL/Dependabot are GitHub-hosted services with no
                                                                        # standalone local equivalent, unlike bandit/pip_audit
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
`scripts/generate_synthetic_data.py` only *writes* `supabase/seed.sql` — it does not load it —
`scripts/populate_openmetadata_tables.py` is a real dependency of four later steps (they fetch table
entities from the catalog and silently no-op if it hasn't run), not an optional extra, and
`npm run supabase:db:reset` always resets the `postgres` role's password back to the Supabase CLI's
fixed local-dev default (there is no `config.toml` option to change this), silently overriding
`POSTGRES_PASSWORD` in `.env` — every later step connecting as the superuser over a native
psycopg2/TCP connection (not `docker exec ... psql`, which uses unaffected local trust auth) fails
authentication until `scripts/sync_postgres_superuser_password.py` re-syncs it:

```bash
python3 scripts/generate_synthetic_data.py                    # writes supabase/seed.sql (does not load it)
npm run supabase:db:reset                                      # applies migrations + loads the seed above
python3 scripts/sync_postgres_superuser_password.py            # re-syncs postgres's password after the reset (idempotent) -- see scripts/sync_postgres_superuser_password.py
python3 scripts/configure_readonly_role.py                     # sets the mcp_readonly role's password (idempotent)
python3 scripts/build_knowledge_graph.py --yes                # load PostgreSQL data into Neo4j (--yes confirms the graph wipe non-interactively)
python3 scripts/populate_openmetadata_tables.py                # register tables -- required before the 4 lines below
python3 scripts/automate_openmetadata_pii_and_profiling.py    # PII tagging + profiling
python3 scripts/ground_fibo_ontology_uris.py                  # link catalog entities to W3C FIBO URIs
python3 scripts/register_openmetadata_data_contracts.py       # publish domains + ODCS-style contracts from contracts/
python3 scripts/execute_openmetadata_data_quality_tests.py    # register + run data quality assertions
python3 scripts/sync_end_to_end_lineage.py                    # PostgreSQL -> Cube.js -> Neo4j lineage DAGs, with
                                                                # real column-level lineage parsed from cube/model/cubes/*.yml
python3 scripts/generate_vector_embeddings.py                 # embed + index into pgvector (HNSW) -- genuinely last
```

The four PII/FIBO/contracts/quality-test lines are mutually independent (each depends only on
`populate_openmetadata_tables.py`, not on each other) and can run in parallel if pipeline runtime
matters. `scripts/bootstrap_platform.sh` runs this entire sequence, plus starting Postgres and Docker
Compose, in one command. `orchestration/definitions.py` encodes the same sequence as a real Dagster
asset graph instead — each script is one `@asset`, dependencies are declared (not just documented in
prose), independent assets actually run concurrently, and every run gets retries, backfill, and
persisted history for free; see `orchestration/README.md`.

Then `scripts/hybrid_rag_retriever.py`, `scripts/ollama_agentic_tool_runner.py`, and `streamlit run scripts/rag_explorer_dashboard.py` operate against the fully-loaded stack.

## Architecture

### Layered stack (bottom to top)

1. **Ingestion** — `scripts/generate_synthetic_data.py` seeds BIAN/FIBO records into PostgreSQL `ref`/`financial` schemas defined by the Supabase migrations in `supabase/migrations/`.
2. **Storage** — Supabase PostgreSQL+pgvector (`:54322`), Neo4j 5 (`:7687`), MySQL (OpenMetadata's backend DB).
3. **Semantic & governance** — Cube.js cubes in `cube/model/cubes/*.yml` (`:4000`), including `ref_country`/`ref_currency`/`ref_nace_industry` (explicit schema-qualified `sql_table:`, since `CUBEJS_DB_SCHEMA=financial` only affects introspection) joined into the party/deposit/loan cubes for AML/country/industry slicing, plus 4 `pre_aggregations` rollups served by the dev-mode image's bundled `cubestore-dev` (no separate Cube Store service needed — see `docker-compose.yml`'s `cube` service comments) and a real `customer_360` view (`cube/model/cubes/views/customer_360.yml`) combining customer/deposit/loan data — replacing the previously-inert, fully-commented-out scaffolding stub. Special-category PII dimensions (`date_of_birth`, `gender`, `id_number`, `registration_number` — classified via the shared `scripts/_pii_classification.py`) are marked `public: false` *and* actually blocked at query time by `cube/cube.js`'s `queryRewrite` — verified live that `public: false` alone only hides a field from GraphQL/Playground introspection in this Cube.js version, never the REST `/load` query path, so `queryRewrite`'s own `MASKED_PII_MEMBERS` list (kept in sync with the YAML via `tests/test_pii_cube_enforcement.py`) is the real enforcement. OpenMetadata catalog (`:8585`) with domains/contracts under `contracts/*.yaml`; W3C FIBO ontology grounding (`ontology/*.ttl`).
4. **Retrieval** — `scripts/hybrid_rag_retriever.py` is the orchestrator: it fuses pgvector HNSW vector search, `scripts/neural_reranker.py` cross-encoder re-ranking, `scripts/text_to_cypher_builder.py` NL→Cypher compilation, Cube.js metrics, and raw SQL into a single "4-tier hybrid RAG" call.
5. **Agentic protocol** — `mcp_server/financial_data_mcp_server.py` is a FastMCP server exposing 6 tools (`search_data_catalog`, `query_semantic_metrics`, `query_knowledge_graph`, `query_financial_database`, `check_data_quality`, `hybrid_rag_search`), runnable over stdio or as the `mcp_sidecar` SSE container (`:8001/sse`, `MCP_TRANSPORT=sse`). `query_financial_database`/`query_knowledge_graph` redact every returned row via `AISafetyGuardrails.redact_rows` (field-aware, by real column/property name against `scripts/_pii_classification.py`'s shared patterns — not a value-shape guess) before returning it, and both tools' exception handlers return a generic message rather than the raw exception text, which previously leaked connection/schema details. `scripts/ollama_agentic_tool_runner.py` drives these tools autonomously via a local Ollama model; its system prompt explicitly frames every tool result as untrusted data, and separately, `AISafetyGuardrails.sanitize_context_payload` (used by `hybrid_rag_search`) now actually quarantines detected prompt-injection spans instead of only flagging them in metadata nothing consumed. Both this file and `scripts/hybrid_rag_retriever.py` reach Postgres/Neo4j via native drivers (`psycopg2`, `neo4j`), not `docker exec` — the `mcp_sidecar` container has neither the `docker` CLI nor a mounted `docker.sock`, so a `docker exec`-based approach fails there specifically even though it works fine when the same code runs directly on the host. The standalone pipeline scripts in `scripts/` are meant to be run on the host; most still use `docker exec` for read-only queries, which is fine there — but any script that *writes* has been migrated to a native driver instead (`generate_vector_embeddings.py`'s INSERT, `build_knowledge_graph.py`'s and `sync_end_to_end_lineage.py`'s Cypher), both to close the `docker.sock` exposure and because `docker exec`'s shelled-out-string-building was the shape of the C6 injection findings; see `scripts/_neo4j_conn.py`.
6. **Consumption & observability** — Streamlit dashboard (`scripts/rag_explorer_dashboard.py`, `:8501`); Grafana (`:3000`) + Prometheus (`:9090`) scraping real metrics served directly by `mcp_sidecar` (`:8000/metrics`, via `prometheus_client.start_http_server()` in `mcp_server/financial_data_mcp_server.py`'s `main()`) — there is no separate telemetry exporter container; metrics live in the same process that executes tool calls, since Prometheus client objects don't share state across processes. Prometheus also scrapes `node_exporter` (`:9100`, host metrics), `postgres_exporter` (`:9187`, connects as the `mcp_readonly` role), `mysqld_exporter` (`:9104`), `cadvisor` (`:8081`, container metrics — per-container discovery doesn't work in every environment, see `docker-compose.yml`'s `cadvisor` service comment; falls back to the aggregate root-cgroup metric), and a JVM-only Neo4j exporter (`:9101`, a `jmx_prometheus_javaagent` attached in-process via `NEO4J_server_jvm_additional` — Neo4j *Community* has no native Prometheus reporter, that's Enterprise-only). `catalog/prometheus_rules.yml` defines real alert rules evaluated against these; `alertmanager` (`:9093`, config in `catalog/alertmanager.yml`) receives them — its receiver is a deliberate no-op (`local-null`) since no real notification channel (SMTP/Slack/etc.) is configured anywhere in this repo, not a broken/fake one; alerts are still visible via Alertmanager's own UI/API and a provisioned Grafana datasource. Real distributed tracing (`scripts/_otel_tracing.py`) runs alongside the metrics: every MCP tool call gets a real OTel span (via `track_tool_call`), and `hybrid_rag_search` additionally gets one child span per RAG tier (Vector/Graph/Semantic/SQL), all correctly nested under the tool-call span via OTel's own context propagation — no explicit wiring between the two modules needed. Spans export via OTLP/gRPC to the `otel_collector` service (`:4317`), which forwards to `tempo` (`:3200` query API) for storage and TraceQL querying through a provisioned Grafana datasource. Fails open by design (`OTEL_TRACES_ENABLED=0` opts out entirely) — a missing/unreachable collector must never break a tool call. Cross-cutting: `scripts/ai_safety_guardrails.py` (PII redaction, prompt-injection defense, read-only query enforcement) and `scripts/llmops_telemetry.py` (per-tier latency tracing feeding the process-global Prometheus metrics, the real OTel spans above, and a per-call JSON trace view), used by the retrieval/agentic layers above. `scripts/llm_judge_evaluator.py` scores `evaluate_agentic_retrieval.py`'s RAG Triad benchmarks via the local `gemma4:latest` Ollama model instead of `rag_triad_evaluator.py`'s substring-overlap fallback (used only when Ollama is unreachable) — see its module docstring for why an empty response needs a deterministic code-level short-circuit rather than a prompt instruction (verified live: the judge model itself doesn't reliably self-correct on that case).

### Data domains

Three BIAN/FIBO-aligned domains, each with its own OpenMetadata data product and ODCS contract under `contracts/`: `Party_Customer_Domain`, `Deposit_Liquidity_Domain`, `Loan_Credit_Risk_Domain`. Table and cube names are strictly prefixed by domain (`party_*`, `deposit_*`, `loan_*`, `ref_*`). The full relational schema is documented in `schema.dbml`; tables follow Inmon 3NF with SCD Type 2 temporal headers. `contracts/*.yaml` covers all 16 real `financial.*` tables (3/6/5/5 per domain) and is the genuine source of truth for both the OpenMetadata data product descriptions and the MCP `financial://data-contracts/slas` resource — both are generated from the parsed YAML at call time via the shared `scripts/_contracts.py`, not hand-duplicated (D2 in the hardening plan). SCD Type 2 close-and-insert itself (locking the active row, closing it, inserting the new version with adjacent, non-overlapping validity ranges) is implemented generically for all 7 business-key tables in `scripts/_scd2.py`'s `scd2_update()`, demonstrated live against the real database by `scripts/demo_scd2_update.py` (D3) — this is a reusable utility with no caller yet in the batch/seed-based pipeline, not a hook wired into `generate_synthetic_data.py`.

`financial`/`ref` are not exposed through Supabase's PostgREST API (removed from `supabase/config.toml`'s `[api].schemas` — nothing in the platform uses that surface) and have Row-Level Security enabled with no policies for the `anon`/`authenticated` Supabase roles, so neither can read a row even if a schema were re-added there by mistake. Application code reaches Postgres over the wire protocol on `[db].port` (`:54322`) directly, either as the `postgres` superuser (pipeline scripts, Cube.js) or as the least-privilege `mcp_readonly` role (MCP server, hybrid RAG retriever — see above).

### Docker networking

`docker-compose.yml` runs most services with `network_mode: "host"` (Neo4j, Cube.js, Prometheus, Grafana, MCP sidecar, the tracing pair `tempo`/`otel_collector`, `alertmanager`, and the exporters `node_exporter`/`postgres_exporter`/`mysqld_exporter`/`cadvisor`) — only the OpenMetadata trio (MySQL, OpenSearch, server) uses bridge networking with published ports. Host-mode services reach each other over `127.0.0.1`, not Docker DNS names; keep this in mind when adding a service or debugging connectivity. Migrating these host-mode services onto bridge networking was assessed and deliberately deferred (see the comment block at the top of `docker-compose.yml`) — it needs `host.docker.internal`/`extra_hosts` to reach the host-run Postgres, plus consistent updates to `catalog/prometheus.yml`'s scrape targets and every `catalog/grafana/provisioning/datasources/*.yml` URL, not a one-line toggle.

MySQL (`33060`), OpenSearch (`9200`), and `openmetadata_server` (`8585`, via `OPENMETADATA_HOST`, default `127.0.0.1`) all publish to `127.0.0.1` only, not `0.0.0.0` — reachable from the host for local debugging/UI access, but not from the network (OpenSearch in particular runs with `DISABLE_SECURITY_PLUGIN=true`, so it must never be exposed beyond localhost; same `MCP_HOST`-style configurable-but-secure-by-default pattern as `OPENMETADATA_HOST`, in case LAN access to the catalog UI is deliberately wanted). Every service except `tempo`/`otel_collector` declares a `healthcheck:` — both of those images are deliberately minimal/distroless (no shell, wget, curl, or nc; verified via `docker run --entrypoint sh ...` failing on both) with no way to express a Docker-native healthcheck, so they rely on `restart: always` alone; `depends_on` targeting either uses `condition: service_started` rather than `service_healthy` for exactly that reason. `openmetadata_server` waits on `openmetadata_db`/`openmetadata_search`, `mcp_sidecar` waits on `neo4j`+`cube`, `grafana` waits on `prometheus` (`service_healthy`) and `tempo` (`service_started`), and `otel_collector` waits on `tempo` (`service_started`). Every service also sets `security_opt: no-new-privileges:true` and a bounded `logging:` driver (10MB × 3 files); config bind mounts (Cube.js's model/`cube.js`, Prometheus's config, Grafana's provisioning, `tempo.yaml`, `otel-collector-config.yaml`) are `:ro`; Prometheus, Grafana, and Tempo persist to named volumes (`prometheus_data`/`grafana_data`/`tempo_data`) rather than losing all history on every container recreate.

### Secrets convention

All credentials (JWT tokens, DB passwords, API secrets) must come from `os.getenv(...)` with an empty-string default — never hardcode a fallback value, even as the `os.getenv` default. (This exact mistake previously shipped a live, non-expiring OpenMetadata bot JWT hardcoded into 8 files, and later recurred as a hardcoded `password12345` Neo4j fallback and a hardcoded MySQL default in `docker-compose.yml` — both since removed.) Real values live only in `.env` (gitignored); `.env.example` holds placeholders.

The MCP SSE endpoint (`mcp_sidecar`, `:8001`) and the Cube.js semantic layer (`:4000`) both enforce real authentication now — `MCP_API_KEY` (bearer token, checked by `BearerAuthMiddleware` in `mcp_server/financial_data_mcp_server.py`) and `CUBEJS_API_SECRET` (bearer token, checked by `cube/cube.js`'s `checkAuth`, in both `CUBEJS_DEV_MODE` settings) respectively. Neither has a hardcoded fallback; in SSE mode an unset `MCP_API_KEY` makes the server refuse to start at all (fail closed, not open), and an unset `CUBEJS_API_SECRET` makes Cube.js reject every request. The MCP server and `scripts/hybrid_rag_retriever.py` also connect to Postgres as a dedicated non-superuser role (`mcp_readonly`, `MCP_PG_READONLY_USER`/`PASSWORD`) rather than the `postgres` superuser used elsewhere in the pipeline — see `supabase/migrations/20260807151500_create_mcp_readonly_role.sql`.

Beware: `openmetadata_server` reads its DB password from the env var `DB_USER_PASSWORD`, not `DB_PASSWORD` — the image's own config template silently falls back to a hardcoded default password if the wrong var name is set. `docker-compose.yml` sets the correct name; if you ever see `Access denied for user 'openmetadata_user'` despite a verified-correct password, check that first.

Beware also: the shared connection-helper modules (`scripts/_neo4j_conn.py`, `scripts/_openmetadata_client.py`, `scripts/_embedding_backend.py`) read their env config at *import time*, not lazily — so each must be imported *after* `scripts._dotenv_boot.load_env()` has run in the importing script, or it silently captures empty credentials. This bit twice during Phase 3's development (a `Neo.ClientError.Security.Unauthorized` from `_neo4j_conn` being imported too early) before the fix; every affected file now has an explicit comment at the import site.

Beware also: `npm run supabase:db:reset` always resets the `postgres` role's TCP password back to the Supabase CLI's fixed local-dev default, overriding `POSTGRES_PASSWORD` in `.env` — there's no `config.toml` setting for a custom local superuser password. Run `python3 scripts/sync_postgres_superuser_password.py` right after every reset (both `scripts/bootstrap_platform.sh` and `orchestration/definitions.py` already do). Also note `postgres` isn't Postgres's actual superuser in Supabase's role model (`rolsuper = false`; `supabase_admin` is the real one) — a plain `ALTER USER postgres WITH PASSWORD ...` run *as* `postgres` fails with `permission denied to alter role ... Only superusers can alter privileged roles`, which is why that script connects as `supabase_admin` to perform the fix.

### Further reading

- `docs/ARCHITECTURE.md` — high-level architecture, data model design, BIAN/FIBO domain alignment, and roadmap.
- `docs/APPLICATION_RUNBOOK.md` — full service inventory, script-by-script deep dive, troubleshooting guide, known issues.
