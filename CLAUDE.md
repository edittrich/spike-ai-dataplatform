# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Enterprise AI-Enabled Data Platform (PoC): a BIAN/FIBO-aligned financial data platform combining a 3NF PostgreSQL core (Supabase + pgvector), a Cube.js semantic layer, a Neo4j knowledge graph, an OpenMetadata catalog, and a FastMCP server that exposes the whole stack as tools to AI agents. There is no application build step — the platform is a set of standalone Python scripts and Docker services wired together at runtime via `.env`.

## Commands

### Environment setup

```bash
cp .env.example .env   # then fill in POSTGRES_PASSWORD, OPENMETADATA_JWT_TOKEN, OPENMETADATA_MYSQL_PASSWORD,
                        # CUBEJS_API_SECRET, CUBEJS_API_SECRET_RESTRICTED, NEO4J_PASSWORD,
                        # GRAFANA_ADMIN_PASSWORD, MCP_API_KEY, MCP_PG_READONLY_PASSWORD,
                        # CUBE_PG_READONLY_PASSWORD, OPENMETADATA_ADMIN_EMAIL, OPENMETADATA_ADMIN_PASSWORD
```

`OPENMETADATA_MYSQL_PASSWORD` and `MCP_API_KEY` have no fallback default — leaving either unset breaks `openmetadata_server` (MySQL auth failure) or, in SSE mode, makes the MCP server refuse to start at all (it fails closed rather than falling back to unauthenticated), respectively. See `docker-compose.yml`'s comments on `DB_USER_PASSWORD` and `mcp_server/financial_data_mcp_server.py`'s `BearerAuthMiddleware` for why. `MCP_PG_READONLY_PASSWORD` and `CUBE_PG_READONLY_PASSWORD` also have no fallback — the MCP server/`scripts/hybrid_rag_retriever.py` and Cube.js respectively connect to Postgres as their own least-privilege role (`mcp_readonly`/`cube_readonly`, not the superuser), neither of whose passwords are set by its migration; both must be applied once via `python3 scripts/configure_readonly_role.py`. `CUBEJS_API_SECRET_RESTRICTED` also has no fallback and, like `CUBEJS_API_SECRET`, must be set or Cube.js refuses to authenticate any request. `OPENMETADATA_ADMIN_EMAIL`/`OPENMETADATA_ADMIN_PASSWORD` are used only by `scripts/rotate_openmetadata_bot_token.py` to mint/renew the OpenMetadata ingestion-bot's JWT.

Also run once per checkout, before your first commit:

```bash
pip install pre-commit
pre-commit install
```

This installs a local git hook (`.pre-commit-config.yaml` -> `scripts/git-hooks/gitleaks-pre-commit.sh`) that runs `gitleaks protect --staged` via Docker on every `git commit`, blocking it if a likely secret is found in the staged diff. No local `gitleaks` binary or Go toolchain needed, only Docker (which the platform already requires). CI separately runs an informational full-history gitleaks scan.

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

### Syntax check / verification

`tests/` is a real pytest suite led by negative security tests: it asserts every guardrail bypass attempt (Cypher `SET`/`REMOVE`/`MERGE`/`CALL`, SQL `pg_read_file`/`COPY ... TO PROGRAM`/stacked statements) is rejected, that `BearerAuthMiddleware` fail-closed behavior holds (401 on missing/wrong/non-ASCII token, 200 on the correct one), and that `contracts/*.yaml` has no column/`allowed_values` drift against the live migration SQL. Two of its files (`test_postgres_readonly_role.py`, `test_schema_dbml_drift.py`) additionally run live checks against the `mcp_readonly` role / the DB-introspected schema when a database is reachable, and skip cleanly (not fail) when it isn't — e.g. in CI, which has no Postgres service. Pipeline scripts themselves still verify by running directly — most end in `if __name__ == "__main__": main()` and print a pass/fail summary to stdout rather than using an assert-based framework. These are the exact steps CI (`.github/workflows/ci.yml`) runs on every push/PR to `main`:

```bash
python3 -m py_compile scripts/*.py mcp_server/*.py                    # syntax check
python3 -m ruff check --select E9,F821,F822,F823 scripts mcp_server   # undefined-name/syntax lint (blocking)
python3 -m ruff check --select F scripts mcp_server                   # broader style lint (informational only)
python3 -m pip_audit -r requirements.txt                              # dependency CVE scan (informational only)
python3 -m bandit -r scripts mcp_server -ll                           # Python security static analysis (informational only)
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
python3 scripts/sync_postgres_superuser_password.py            # re-syncs postgres's password after the reset (idempotent)
python3 scripts/configure_readonly_role.py                     # sets the mcp_readonly and cube_readonly roles' passwords (idempotent)
python3 scripts/rotate_openmetadata_bot_token.py               # mints/renews the OpenMetadata ingestion-bot's JWT (idempotent)
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
prose), independent assets run concurrently, and every run gets retries, backfill, and persisted
history for free; see `docs/APPLICATION_RUNBOOK.md`'s Dagster section for setup and usage.

Then `scripts/hybrid_rag_retriever.py`, `scripts/ollama_agentic_tool_runner.py`, and `streamlit run scripts/rag_explorer_dashboard.py` operate against the fully-loaded stack.

## Architecture

### Layered stack (bottom to top)

1. **Ingestion** — `scripts/generate_synthetic_data.py` seeds BIAN/FIBO records into PostgreSQL `ref`/`financial` schemas defined by the Supabase migrations in `supabase/migrations/`.
2. **Storage** — Supabase PostgreSQL+pgvector (`:54322`), Neo4j 5 (`:7687`), MySQL (OpenMetadata's backend DB).
3. **Semantic & governance** — Cube.js cubes in `cube/model/cubes/*.yml` (`:4000`), including `ref_country`/`ref_currency`/`ref_nace_industry` (explicit schema-qualified `sql_table:`, since `CUBEJS_DB_SCHEMA=financial` only affects introspection) joined into the party/deposit/loan cubes for AML/country/industry slicing, plus 4 `pre_aggregations` rollups served by the standalone `cubestore` service and a `customer_360` view (`cube/model/cubes/views/customer_360.yml`) combining customer/deposit/loan data. Special-category PII dimensions (`date_of_birth`, `gender`, `id_number`, `registration_number` — classified via the shared `scripts/_pii_classification.py`) are marked `public: false` and blocked at query time by `cube/cube.js`'s `queryRewrite`, whose `MASKED_PII_MEMBERS` list (kept in sync with the YAML via `tests/test_pii_cube_enforcement.py`) is the real enforcement mechanism — `public: false` alone only hides a field from GraphQL/Playground introspection, not the REST `/load` query path. OpenMetadata catalog (`:8585`) with domains/contracts under `contracts/*.yaml`; W3C FIBO ontology grounding (`ontology/*.ttl`).
4. **Retrieval** — `scripts/hybrid_rag_retriever.py` is the orchestrator: it fuses pgvector HNSW vector search, `scripts/neural_reranker.py` cross-encoder re-ranking, `scripts/text_to_cypher_builder.py` NL→Cypher compilation, Cube.js metrics, and raw SQL into a single "4-tier hybrid RAG" call.
5. **Agentic protocol** — `mcp_server/financial_data_mcp_server.py` is a FastMCP server exposing 6 tools (`search_data_catalog`, `query_semantic_metrics`, `query_knowledge_graph`, `query_financial_database`, `check_data_quality`, `hybrid_rag_search`), runnable over stdio or as the `mcp_sidecar` SSE container (`:8001/sse`, `MCP_TRANSPORT=sse`). `query_financial_database`/`query_knowledge_graph` redact every returned row via `AISafetyGuardrails.redact_rows` (field-aware, by real column/property name against `scripts/_pii_classification.py`'s shared patterns) before returning it, and both tools' exception handlers return a generic message rather than raw exception text. `scripts/ollama_agentic_tool_runner.py` drives these tools autonomously via a local Ollama model; its system prompt frames every tool result as untrusted data, and `AISafetyGuardrails.sanitize_context_payload` (used by `hybrid_rag_search`) quarantines detected prompt-injection spans rather than only flagging them. Both this file and `scripts/hybrid_rag_retriever.py` reach Postgres/Neo4j via native drivers (`psycopg2`, `neo4j`), not `docker exec` — the `mcp_sidecar` container has neither the `docker` CLI nor a mounted `docker.sock`. The standalone pipeline scripts in `scripts/` are meant to be run on the host; most use `docker exec` for read-only queries, which is fine there, but any script that *writes* uses a native driver instead (`generate_vector_embeddings.py`'s INSERT, `build_knowledge_graph.py`'s and `sync_end_to_end_lineage.py`'s Cypher) — see `scripts/_neo4j_conn.py`.
6. **Consumption & observability** — Streamlit dashboard (`scripts/rag_explorer_dashboard.py`, `:8501`); Grafana (`:3000`) + Prometheus (`:9090`) scraping real metrics served directly by `mcp_sidecar` (`:8000/metrics`, via `prometheus_client.start_http_server()` in `mcp_server/financial_data_mcp_server.py`'s `main()`) — metrics live in the same process that executes tool calls, since Prometheus client objects don't share state across processes. Prometheus also scrapes `node_exporter` (`:9100`, host metrics), `postgres_exporter` (`:9187`, connects as the `mcp_readonly` role), `mysqld_exporter` (`:9104`), `cadvisor` (`:8081`, container metrics — falls back to the aggregate root-cgroup metric where per-container discovery doesn't work in a given environment), and a JVM-only Neo4j exporter (`:9101`, a `jmx_prometheus_javaagent` attached in-process via `NEO4J_server_jvm_additional` — Neo4j *Community* has no native Prometheus reporter, that's Enterprise-only). `catalog/prometheus_rules.yml` defines alert rules evaluated against these; `alertmanager` (`:9093`, config in `catalog/alertmanager.yml`) receives them — its receiver is a deliberate no-op (`local-null`) since no real notification channel (SMTP/Slack/etc.) is configured anywhere in this repo; alerts are still visible via Alertmanager's own UI/API and a provisioned Grafana datasource. Distributed tracing (`scripts/_otel_tracing.py`) runs alongside the metrics: every MCP tool call gets an OTel span (via `track_tool_call`), and `hybrid_rag_search` additionally gets one child span per RAG tier (Vector/Graph/Semantic/SQL), nested under the tool-call span via OTel's own context propagation. Spans export via OTLP/gRPC to the `otel_collector` service (`:4317`), which forwards to `tempo` (`:3200` query API) for storage and TraceQL querying through a provisioned Grafana datasource. Fails open by design (`OTEL_TRACES_ENABLED=0` opts out entirely). Cross-cutting: `scripts/ai_safety_guardrails.py` (PII redaction, prompt-injection defense, read-only query enforcement) and `scripts/llmops_telemetry.py` (per-tier latency tracing feeding the process-global Prometheus metrics, the OTel spans above, and a per-call JSON trace view), used by the retrieval/agentic layers above. `scripts/llm_judge_evaluator.py` scores `evaluate_agentic_retrieval.py`'s RAG Triad benchmarks via the local `gemma4:latest` Ollama model, falling back to `rag_triad_evaluator.py`'s substring-overlap scorer only when Ollama is unreachable.

### Data domains

Three BIAN/FIBO-aligned domains, each with its own OpenMetadata data product and ODCS contract under `contracts/`: `Party_Customer_Domain`, `Deposit_Liquidity_Domain`, `Loan_Credit_Risk_Domain`. Table and cube names are strictly prefixed by domain (`party_*`, `deposit_*`, `loan_*`, `ref_*`). The full relational schema is documented in `schema.dbml`; tables follow Inmon 3NF with SCD Type 2 temporal headers. `contracts/*.yaml` covers all 16 real `financial.*` tables (3/6/5/5 per domain) and is the source of truth for both the OpenMetadata data product descriptions and the MCP `financial://data-contracts/slas` resource — both are generated from the parsed YAML at call time via the shared `scripts/_contracts.py`. SCD Type 2 close-and-insert (locking the active row, closing it, inserting the new version with adjacent, non-overlapping validity ranges) is implemented generically for all 7 business-key tables in `scripts/_scd2.py`'s `scd2_update()`, demonstrated against the real database by `scripts/demo_scd2_update.py` — a reusable utility with no caller yet in the batch/seed-based pipeline.

`financial`/`ref` are not exposed through Supabase's PostgREST API (excluded from `supabase/config.toml`'s `[api].schemas` — nothing in the platform uses that surface) and have Row-Level Security enabled with no policies for the `anon`/`authenticated` Supabase roles, so neither can read a row even if a schema were re-added there by mistake. Application code reaches Postgres over the wire protocol on `[db].port` (`:54322`) directly, either as the `postgres` superuser (pipeline scripts, Cube.js's setup) or as the least-privilege `mcp_readonly` role (MCP server, hybrid RAG retriever) or `cube_readonly` role (Cube.js's own runtime queries).

### Docker networking

Every service in `docker-compose.yml` joins one user-defined bridge network, `platform_network`.
Services reach each other via Docker Compose's service-name DNS (`neo4j:7687`, `cube:4000`,
`prometheus:9090`, `tempo:3200`, `otel_collector:4317`, `openmetadata_server:8585`, ...) rather than
`127.0.0.1` — `catalog/prometheus.yml`'s scrape targets and its `alerting:` block, and every
`catalog/grafana/provisioning/datasources/*.yml` URL, point at these service names. PostgreSQL isn't a
compose service, so the 3 services that need it (`cube`, `postgres_exporter`, `mcp_sidecar`) reach it
via `extra_hosts: ["host.docker.internal:host-gateway"]` — required explicitly on Linux (unlike
Docker Desktop).

Every service that has an explicit internal bind-address flag/env var (Neo4j's JMX exporter,
`cubestore`'s 3 ports, `node_exporter`, `postgres_exporter`, `mysqld_exporter`, `cadvisor`,
`alertmanager`) binds internally to `0.0.0.0` — safe under bridge networking, since "reachable by
peers on `platform_network`" is not the same as "reachable from the LAN" — and controls host/LAN
exposure exclusively via the `ports:` mapping's host-side address: `127.0.0.1:<port>:<port>` limits it
to the host itself; a service with no `ports:` entry at all (`cubestore`) is reachable by nothing
outside `platform_network`.

`MCP_HOST` controls only the *host-side* interface `docker-compose.yml`'s `ports:` publishes
`mcp_sidecar`'s 8001/8000 to (`${MCP_HOST:-127.0.0.1}:8001:8001`, evaluated by Compose itself before
container creation) — the container's own internal bind is hardcoded to `0.0.0.0` in its
`environment:` block. If you run `financial_data_mcp_server.py`'s SSE mode directly on a host instead
of in Docker, `MCP_HOST` controls that process's own bind address directly — see `.env.example`'s
comment on it. The same pattern applies to `cube`'s and `mcp_sidecar`'s other internal env vars
(`CUBEJS_DB_HOST`, `NEO4J_URI`, `CUBEJS_URL`, `OPENMETADATA_URL`, `OTEL_EXPORTER_OTLP_ENDPOINT`): each
is hardcoded to the correct service name or `host.docker.internal` directly in that service's own
`environment:` block rather than derived from `.env` via `${VAR:-default}`, so a host-oriented `.env`
default is never inherited inside a container where it would resolve to the wrong address. `.env`'s
own `127.0.0.1`-based defaults for these same variable names are what host-run pipeline scripts use,
and those scripts reach every service correctly via Docker's published ports.

Any `healthcheck:` that targets `127.0.0.1:<own-port>` (the large majority) runs `docker exec`-style
inside the container it's checking, so it's checking itself regardless of network mode.

MySQL (`33060`), OpenSearch (`9200`), and `openmetadata_server` (`8585`, via `OPENMETADATA_HOST`,
default `127.0.0.1`) all publish to `127.0.0.1` only, not `0.0.0.0` — reachable from the host for
local debugging/UI access, but not from the network (OpenSearch in particular runs with
`DISABLE_SECURITY_PLUGIN=true`, so it must never be exposed beyond localhost). Every host-facing port
in the file (Neo4j Browser/Bolt, Cube.js, Prometheus, Grafana, Tempo's query API, the OTLP receivers,
every exporter, Alertmanager, `mcp_sidecar`'s SSE/metrics ports) follows the identical
`127.0.0.1:<port>:<port>` convention for the same reason.

Every service except `tempo`/`otel_collector` declares a `healthcheck:` — both of those images are
minimal/distroless (no shell, wget, curl, or nc) with no way to express a Docker-native healthcheck,
so they rely on `restart: always` alone; `depends_on` targeting either uses `condition:
service_started` rather than `service_healthy` for that reason. `openmetadata_server` waits on
`openmetadata_db`/`openmetadata_search`, `mcp_sidecar` waits on `neo4j`+`cube`, `grafana` waits on
`prometheus` (`service_healthy`) and `tempo` (`service_started`), and `otel_collector` waits on
`tempo` (`service_started`). Every service sets `security_opt: no-new-privileges:true` and a bounded
`logging:` driver (10MB × 3 files); config bind mounts (Cube.js's model/`cube.js`, Prometheus's
config, Grafana's provisioning, `tempo.yaml`, `otel-collector-config.yaml`) are `:ro`; Prometheus,
Grafana, and Tempo persist to named volumes (`prometheus_data`/`grafana_data`/`tempo_data`) rather
than losing history on every container recreate. Every service except `neo4j_jmx_agent_init` (a
one-shot init container) also sets `read_only: true` on the root filesystem, with an explicit,
per-image-audited `tmpfs`/writable-mount allowlist for whatever it genuinely needs to write — see
`docker-compose.yml`'s own top-of-file comment for two non-obvious Docker `tmpfs` pitfalls (default
non-writable ownership for a non-root container user; the `mode:` field expecting the *decimal* value
equal to the intended *octal* permission bits). `cap_drop`/`pids_limit`/CPU limits are not currently
set on any service.

### Secrets convention

All credentials (JWT tokens, DB passwords, API secrets) must come from `os.getenv(...)` with an empty-string default — never hardcode a fallback value, even as the `os.getenv` default. Real values live only in `.env` (gitignored, mode `600`); `.env.example` holds placeholders.

The MCP SSE endpoint (`mcp_sidecar`, `:8001`) and the Cube.js semantic layer (`:4000`) both enforce authentication — `MCP_API_KEY` (bearer token, checked by `BearerAuthMiddleware` in `mcp_server/financial_data_mcp_server.py`) and two bearer tokens checked by `cube/cube.js`'s `checkAuth` via `crypto.timingSafeEqual`: `CUBEJS_API_SECRET` (privileged role — full semantic-layer access) and `CUBEJS_API_SECRET_RESTRICTED` (restricted role — general BIAN/FIBO access; `queryRewrite`'s `AML_RESTRICTED_MEMBERS` blocks AML risk classification fields for this role specifically, a real row-level authorization boundary, not just authentication). Neither `MCP_API_KEY` nor either Cube.js secret has a hardcoded fallback; in SSE mode an unset `MCP_API_KEY` makes the server refuse to start at all, and an unset `CUBEJS_API_SECRET`/`CUBEJS_API_SECRET_RESTRICTED` makes Cube.js reject every request. `cube` runs in production mode (`CUBEJS_DEV_MODE=false`) against a standalone single-instance `cubestore` service (`cubejs/cubestore:v1.7.17`, also acting as its own refresh worker via `CUBEJS_REFRESH_WORKER=true` so `pre_aggregations` rollups build). The MCP server, `scripts/hybrid_rag_retriever.py`, and Cube.js itself all connect to Postgres as dedicated non-superuser roles (`mcp_readonly`/`cube_readonly` — `MCP_PG_READONLY_USER`/`PASSWORD` and `CUBE_PG_READONLY_USER`/`PASSWORD`) rather than the `postgres` superuser used elsewhere in the pipeline — see `supabase/migrations/20260807151500_create_mcp_readonly_role.sql` and `20260808150000_create_cube_readonly_role.sql`; configure both roles' passwords with `python3 scripts/configure_readonly_role.py`.

Beware: `openmetadata_server` reads its DB password from the env var `DB_USER_PASSWORD`, not `DB_PASSWORD` — the image's own config template silently falls back to a hardcoded default password if the wrong var name is set. `docker-compose.yml` sets the correct name; if you ever see `Access denied for user 'openmetadata_user'` despite a verified-correct password, check that first.

Beware also: the shared connection-helper modules (`scripts/_neo4j_conn.py`, `scripts/_openmetadata_client.py`, `scripts/_embedding_backend.py`) read their env config at *import time*, not lazily — so each must be imported *after* `scripts._dotenv_boot.load_env()` has run in the importing script, or it silently captures empty credentials.

Beware also: `npm run supabase:db:reset` always resets the `postgres` role's TCP password back to the Supabase CLI's fixed local-dev default, overriding `POSTGRES_PASSWORD` in `.env` — there's no `config.toml` setting for a custom local superuser password. Run `python3 scripts/sync_postgres_superuser_password.py` right after every reset (both `scripts/bootstrap_platform.sh` and `orchestration/definitions.py` already do). Also note `postgres` isn't Postgres's actual superuser in Supabase's role model (`rolsuper = false`; `supabase_admin` is the real one) — a plain `ALTER USER postgres WITH PASSWORD ...` run *as* `postgres` fails with `permission denied to alter role ... Only superusers can alter privileged roles`, which is why that script connects as `supabase_admin` to perform the fix.

Beware also: `OPENMETADATA_JWT_TOKEN` (the `ingestion-bot`'s credential) is a time-bounded 90-day token, not a permanent one; letting it expire breaks catalog writes and the MCP `search_data_catalog` tool. `python3 scripts/rotate_openmetadata_bot_token.py` checks/renews it (idempotent, no-ops unless expiring within 14 days; needs `OPENMETADATA_ADMIN_EMAIL`/`OPENMETADATA_ADMIN_PASSWORD` in `.env` to actually mint a new one) and is wired into `scripts/bootstrap_platform.sh` and a daily Dagster schedule (`orchestration/definitions.py`'s `bot_token_rotation_daily`). A freshly-minted bot token can also take up to roughly a minute before OpenMetadata's own internal auth cache recognizes it on every API path — an immediate call right after rotation can 401 once, then succeed on retry a few seconds later.

### Further reading

- `docs/ARCHITECTURE.md` — high-level architecture, data model design, BIAN/FIBO domain alignment, and the security model.
- `docs/APPLICATION_RUNBOOK.md` — full service inventory, script-by-script deep dive, troubleshooting guide, known operational quirks.
- `docs/PLATFORM_ANALYSIS_PLAN.md` — the single source of truth for platform analysis: per-dimension findings, the ranked issue list, the accepted-limitations register, proposed capabilities, and the phased remediation plan.
