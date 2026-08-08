# Enterprise AI Data Platform: Application Runbook

Welcome to the **Enterprise AI Data Platform**! This Application Runbook is designed as an exhaustive technical reference and operational guide for software engineers. It covers Docker container topologies, script implementations, open-source references, and daily operational workflows.

For the high-level architecture, data model, and design rationale, see
[`ARCHITECTURE.md`](ARCHITECTURE.md) instead — this document assumes that context and focuses on
*how to run and operate* the platform.

---

## 📚 Table of Contents
1. [Docker Container Topology & Network Configuration](#1-docker-container-topology--network-configuration)
2. [Script-by-Script Codebase Deep Dive](#2-script-by-script-codebase-deep-dive)
3. [Official Open-Source Documentation References](#3-official-open-source-documentation-references)
4. [Developer Operations & Troubleshooting Runbook](#4-developer-operations--troubleshooting-runbook)
5. [Known Issues](#5-known-issues)

---

## 1. Docker Container Topology & Network Configuration

All services in [`docker-compose.yml`](../docker-compose.yml) join a single user-defined bridge
network, `platform_network` (H4, hardening plan, done 2026-08-08 — `network_mode: "host"` was used
by 13 services before this migration and is now gone from the file entirely). Services reach each
other via Docker Compose's own service-name DNS (`neo4j:7687`, `cube:4000`, `prometheus:9090`, ...)
rather than `127.0.0.1`; host-facing ports are published explicitly via `ports:`, each scoped to
`127.0.0.1:<port>:<port>` unless a service is meant to be human-reachable only (see the per-service
table below for each one's actual publish address). **PostgreSQL is the one exception** — it is
*not* a `docker-compose.yml` service. It is managed by the Supabase CLI (`npm run supabase:start`,
wrapping `supabase start`), which runs its own Postgres container (image
`supabase/postgres:15.1.0.147`, published on `127.0.0.1:54322`) plus its own scratch state under
`supabase/.temp/`. Start it *before* `docker compose up -d` — the 3 services that need it
(`cube`, `postgres_exporter`, `mcp_sidecar`) reach it via `extra_hosts:
["host.docker.internal:host-gateway"]` (required explicitly on Linux) rather than `127.0.0.1`, and
will crash-loop against a refused connection until Postgres is up. See `CLAUDE.md`'s "Docker
networking" section for the full migration writeup, including the security-model inversion this
created (a service bound to `127.0.0.1` *internally* is now unreachable by its own bridge peers,
the opposite of host-mode's behavior) and how every affected service's bind address was corrected.

### Active Service Inventory

| Container Name | Service Image | Port | Config / Environment Variables | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `openmetadata_mysql` | `mysql:8.0.35` | `3306` (published loopback-only as `127.0.0.1:33060`) | `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD` (both `${OPENMETADATA_MYSQL_PASSWORD}`, no fallback — required) | OpenMetadata catalog backend database |
| `openmetadata_search` | `opensearchproject/opensearch:2.11.0` | `9200` (published loopback-only as `127.0.0.1:9200`) | `DISABLE_SECURITY_PLUGIN=true` | Catalog search index (security plugin off; only reachable from the host or the internal Docker network, never externally) |
| `openmetadata_server` | `openmetadata/server:1.3.1` | `8585` (published loopback-only as `127.0.0.1:8585` unless `OPENMETADATA_HOST` overrides it) | `OPENMETADATA_URL`, `OPENMETADATA_JWT_TOKEN`, `DB_USER_PASSWORD` (⚠️ not `DB_PASSWORD` — see Troubleshooting) | Enterprise Data Catalog UI & REST API |
| `neo4j_knowledge_graph` | `neo4j:5.18.0-community` | `7474` / `7687`, plus `9101` (bound `127.0.0.1`, JVM-only Prometheus metrics — Neo4j Community has no native reporter, this is a `jmx_prometheus_javaagent` attached in-process via `NEO4J_server_jvm_additional`) | `NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}` (no fallback — required) | Knowledge Graph database & Bolt driver |
| `cube_semantic_layer` | `cubejs/cube:v0.35` | `4000` | `CUBEJS_DB_TYPE=postgres`, `CUBEJS_API_SECRET` — **enforced**: [`cube/cube.js`](../cube/cube.js)'s `checkAuth` rejects any request whose `Authorization: Bearer` token doesn't match this secret, in both dev and production mode. No `CUBEJS_SQL_PORT` — the Postgres-wire SQL API it would open has no equivalent auth check and nothing uses it. | Open-Source Semantic Layer (REST API) |
| `prometheus_metrics` | `prom/prometheus:v2.51.0` | `9090` | [catalog/prometheus.yml](../catalog/prometheus.yml) | Operational time-series metrics engine |
| `grafana_observability_dashboard` | `grafana/grafana:10.4.0` | `3000` | `GF_SECURITY_ADMIN_PASSWORD` | Visual monitoring dashboard portal |
| `mcp_agentic_sidecar` | [`mcp_server/Dockerfile.mcp`](../mcp_server/Dockerfile.mcp) | `8001` (SSE, bound to `127.0.0.1` unless `MCP_HOST` overrides it) and `8000` (`/metrics`) | `MCP_TRANSPORT=sse`, `MCP_PORT=8001`, `MCP_METRICS_PORT=8000`, `MCP_HOST`, `MCP_API_KEY` — required; the SSE endpoint now **refuses to start** without it, rather than falling back to unauthenticated. Connects to Postgres as `MCP_PG_READONLY_USER`/`MCP_PG_READONLY_PASSWORD` (the `mcp_readonly` role), not the superuser. | FastMCP Server SSE HTTP agent daemon **and** the platform's real Prometheus metrics source (`prometheus_client.start_http_server()`); runs as non-root `appuser` |
| `otel_collector` | `otel/opentelemetry-collector:0.158.0` | `4317` (OTLP/gRPC), `4318` (OTLP/HTTP), `13133` (health, host-side only — see below) | [catalog/otel-collector-config.yaml](../catalog/otel-collector-config.yaml) | Receives real trace spans from `mcp_sidecar`, batches, forwards to `tempo` |
| `tempo_tracing_backend` | `grafana/tempo:3.0.2` | `3200` (query API, used by Grafana's datasource), `4319`/`4320` (OTLP receiver, collector-only — see config comment for why these aren't 4317/4318) | [catalog/tempo.yaml](../catalog/tempo.yaml) | Trace storage + TraceQL query backend (monolithic mode, local filesystem storage) |
| `node_exporter` | `prom/node-exporter:v1.8.2` | `9100` (bound `127.0.0.1`) | mounts `/proc`/`/sys`/`/` read-only | Host OS metrics (CPU, memory, disk, filesystem) |
| `postgres_exporter` | `prometheuscommunity/postgres-exporter:v0.15.0` | `9187` (bound `127.0.0.1`) | `DATA_SOURCE_NAME` built from `MCP_PG_READONLY_USER`/`MCP_PG_READONLY_PASSWORD` — connects as the least-privilege role, not the superuser; `--no-collector.wal` (needs a superuser-only function) | Postgres metrics (`pg_up`, connection counts, etc.) |
| `mysqld_exporter` | `prom/mysqld-exporter:v0.15.1` | `9104` (bound `127.0.0.1`) | generates a `.my.cnf` at container startup from `OPENMETADATA_MYSQL_PASSWORD` (v0.15.x removed `DATA_SOURCE_NAME` env-var support) | MySQL metrics (OpenMetadata's backend DB) |
| `cadvisor` | `gcr.io/cadvisor/cadvisor:v0.49.1` | `8081` (bound `127.0.0.1`) | mounts `/var/run/docker.sock:ro` (see the service's own comment on what `:ro` does and doesn't buy) | Container resource metrics — per-container discovery is environment-dependent, see the service comment; falls back to the aggregate root-cgroup metric where it doesn't work |
| `neo4j_jmx_agent_init` | `alpine:3.20` | n/a (one-shot, `restart: "no"`) | downloads `jmx_prometheus_javaagent` (pinned version + sha256) into the `jmx_exporter_agent` named volume | Init container only — populates the jar the `neo4j` service's javaagent needs; not a long-running service |
| `alertmanager` | `prom/alertmanager:v0.27.0` | `9093` (bound `127.0.0.1`) | [catalog/alertmanager.yml](../catalog/alertmanager.yml) — receiver is a deliberate no-op (`local-null`), no real notification channel configured | Receives/dedupes alerts fired by `catalog/prometheus_rules.yml`; alerts visible via its own UI/API and a provisioned Grafana datasource |

There is no separate telemetry-exporter service for *metrics* — `mcp_sidecar` serves real per-call
metrics itself (the process that actually executes tool calls is the only one that can; Prometheus
client objects don't share state across processes, which is exactly why the previous separate
exporter container had to fabricate its data — see [Known Issues](#5-known-issues)). *Traces* do have
a two-service backend (`otel_collector` + `tempo`) because that's genuinely how OTel's reference
architecture separates ingestion/batching from storage/query — see `scripts/_otel_tracing.py`.

Every long-running service except `otel_collector`/`tempo` declares a `healthcheck:` in
`docker-compose.yml` -- both of those images are deliberately minimal/distroless (no shell, wget,
curl, or nc) with no way to express one; `restart: always` is their resilience mechanism instead, and
anything depending on them uses `condition: service_started` rather than `service_healthy`.
`neo4j_jmx_agent_init` is a one-shot init container (`restart: "no"`), not a long-running service, so
it has no healthcheck either -- `neo4j` gates on it via `condition: service_completed_successfully`.
`openmetadata_server` gates on `openmetadata_db`/`openmetadata_search`, `mcp_sidecar` gates on
`neo4j`/`cube`, `cube` itself gates on `cubestore` (H1), `grafana` gates on `prometheus` (healthy) and
`tempo` (started), `otel_collector` gates
on `tempo` (started), and `mysqld_exporter` gates on `openmetadata_db` (healthy) — all via `depends_on`
(fixes real startup races — see Troubleshooting). Every service also sets
`security_opt: no-new-privileges:true` and a bounded `logging:` driver; Prometheus, Grafana, Tempo,
the standalone `cubestore` service (H1 — production mode's real Cube Store, not dev mode's embedded
`cubestore-dev`), and the Neo4j JMX agent's jar persist to named volumes
(`prometheus_data`/`grafana_data`/`tempo_data`/`cubestore_data`/`jmx_exporter_agent`, plus
`alertmanager_data`) instead of losing all history (or, for the two agent/jar cases, having to
re-download/rebuild) on every recreate; config bind mounts (Cube.js's model/`cube.js`, Prometheus's
config + rules, Grafana's provisioning, `tempo.yaml`, `otel-collector-config.yaml`,
`alertmanager.yml`, `neo4j_jmx_exporter_config.yml`) are `:ro`.

---

## 2. Script-by-Script Codebase Deep Dive

> **Shortcut:** [`scripts/bootstrap_platform.sh`](../scripts/bootstrap_platform.sh) runs every step
> below in the correct order, once, from an empty checkout — starting Postgres, applying migrations,
> seeding data, starting Docker Compose, configuring the least-privilege role, and running the full
> catalog/embedding pipeline. Everything in this section documents what it does and why; run it
> directly if you just want the platform up.

### A. Data Ingestion & Data Generation

0. **Prerequisite — initialize the database and the least-privilege role.**
   `generate_synthetic_data.py` (below) only *writes* `supabase/seed.sql`; nothing in the pipeline
   applies the schema or loads that file automatically. Before step 1, run the schema migrations and
   load the seed via the Supabase CLI: `npm run supabase:start` (first time) or
   `npm run supabase:db:reset` (re-seed), both defined in [`package.json`](../package.json). A reset
   also silently resets the `postgres` role's TCP password back to the Supabase CLI's fixed local-dev
   default, overriding `POSTGRES_PASSWORD` in `.env` — run
   [`scripts/sync_postgres_superuser_password.py`](../scripts/sync_postgres_superuser_password.py)
   right after every reset to fix that (idempotent; see its module docstring for the full story,
   including why it connects as `supabase_admin`, not `postgres` itself, to perform the fix). This
   also applies `supabase/migrations/20260807151500_create_mcp_readonly_role.sql`, which creates the
   `mcp_readonly` role the MCP server connects as — its password isn't set by the migration itself
   (checked-in files can't hold real secrets), so also run
   `python3 scripts/configure_readonly_role.py` once `MCP_PG_READONLY_PASSWORD` is set in `.env`.
   Skipping any of this leaves later steps running against an empty database, running against the
   wrong postgres password, or leaves the MCP server unable to authenticate. Also run
   [`scripts/rotate_openmetadata_bot_token.py`](../scripts/rotate_openmetadata_bot_token.py) once
   `openmetadata_server` is up and `OPENMETADATA_ADMIN_EMAIL`/`OPENMETADATA_ADMIN_PASSWORD` are set in
   `.env` — step 2 below and its dependents (steps 4–8) authenticate to OpenMetadata as the
   `ingestion-bot`, whose JWT is a genuinely time-bounded 90-day credential (H10, hardening plan), not
   a permanent one. This script is idempotent (no-ops unless the current token is missing or within 14
   days of expiring), is already wired into `scripts/bootstrap_platform.sh`, and also runs on its own
   daily Dagster schedule (`orchestration/definitions.py`'s `bot_token_rotation_daily`) independent of
   when anyone next runs the pipeline — so this is normally self-maintaining, not something to remember
   to run by hand every 90 days.
1. **[`scripts/generate_synthetic_data.py`](../scripts/generate_synthetic_data.py):** Generates synthetic BIAN/FIBO aligned records and writes them to `supabase/seed.sql`. Does not connect to PostgreSQL itself — see the prerequisite above for how the file actually gets loaded.
2. **[`scripts/populate_openmetadata_tables.py`](../scripts/populate_openmetadata_tables.py):** Registers database services and table metadata into OpenMetadata via REST API. **Required before steps 4–8** — those all fetch table entities from the catalog and no-op silently if this hasn't run.
3. **[`scripts/build_knowledge_graph.py`](../scripts/build_knowledge_graph.py):** Extracts PostgreSQL relational tables and loads them into Neo4j via Cypher transactions; prints the resulting node/relationship counts at the end of each run (deterministic given the seeded synthetic dataset from `generate_synthetic_data.py`, but re-run it for the current number rather than trusting a number written here). Its schema step (constraints + two full-text indexes) reads from committed DDL at [`neo4j/schema/constraints_and_indexes.cypher`](../neo4j/schema/constraints_and_indexes.cypher) rather than hardcoding Cypher inline — the Neo4j analogue of `supabase/migrations/*.sql`. `party_name_fulltext` (over `Individual`/`Organization` name properties) and `reference_name_fulltext` (over `RefCountry`/`RefCurrency`/`RefIndustry`) let an agent resolve a party or reference entity by free-text name instead of requiring an exact code/ID match, e.g. `CALL db.index.fulltext.queryNodes('party_name_fulltext', 'Schmidt') YIELD node, score ...`.

### B. Governance, Lineage & Quality

Steps 4–7 below are mutually independent — each depends only on step 2 having run, not on each other
or on step 3 — and can run in any order or in parallel.

4. **[`scripts/automate_openmetadata_pii_and_profiling.py`](../scripts/automate_openmetadata_pii_and_profiling.py):** Scans columns for sensitive data and attaches PII tags (`PersonalData.Personal`).
5. **[`scripts/ground_fibo_ontology_uris.py`](../scripts/ground_fibo_ontology_uris.py):** Grounds table entities to W3C FIBO class URIs (e.g. `Party` $\rightarrow$ `https://www.omg.org/spec/Commons/PartiesAndSituations/Party` — genuinely defined in a separate OMG "Commons" ontology FIBO itself imports, not under FIBO's own `spec.edmcouncil.org/fibo/ontology/` namespace; see D5 in the hardening plan). All 19 `FIBO_GROUNDING_MAP` entries have been individually verified against the real upstream FIBO source (15 corrected, 4 confirmed correct) — see the map's own module comment for the full per-entry writeup.
6. **[`scripts/register_openmetadata_data_contracts.py`](../scripts/register_openmetadata_data_contracts.py):** Registers 3 formal Data Products & Contracts under `contracts/`, parsing `contracts/*.yaml` as the actual source of truth via the shared `scripts/_contracts.py` (D2) rather than a hand-duplicated markdown copy.
7. **[`scripts/execute_openmetadata_data_quality_tests.py`](../scripts/execute_openmetadata_data_quality_tests.py):** Runs 59 automated data quality assertions across 12 of the platform's 19 tables.
8. **[`scripts/sync_end_to_end_lineage.py`](../scripts/sync_end_to_end_lineage.py):** Syncs table-to-cube and table-to-graph lineage nodes in OpenMetadata. Depends on step 2 (table entities to attach lineage to). Parses the real `cube/model/cubes/*.yml` definitions (not hardcoded placeholder columns) for each `Cube_*` entity's measures/dimensions, and emits real `columnsLineage` (table.column → cube.measure/dimension) wherever a dimension/measure's `sql:` is a bare source-table column reference.

### C. Context, Search & Hybrid RAG Retrieval

9. **[`scripts/generate_vector_embeddings.py`](../scripts/generate_vector_embeddings.py):** Generates 384-dimensional dense vectors using `sentence-transformers/all-MiniLM-L6-v2` and indexes them in `pgvector 0.8.0` HNSW. This is genuinely the last step to run — it reads catalog tables (step 2), data products (step 6), and FIBO tags (step 5).
10. **[`scripts/neural_reranker.py`](../scripts/neural_reranker.py):** Uses PyTorch `cross-encoder/ms-marco-MiniLM-L-6-v2` Cross-Encoder to re-rank 1st-stage vector candidates based on deep cross-attention.
11. **[`scripts/text_to_cypher_builder.py`](../scripts/text_to_cypher_builder.py):** Compiles natural language prompts into read-only Neo4j Cypher queries.
12. **[`scripts/hybrid_rag_retriever.py`](../scripts/hybrid_rag_retriever.py):** 4-tier Hybrid RAG orchestrator combining Vector Search + Cypher + Cube.js Metrics + PostgreSQL SQL.

### D. Guardrails, Telemetry & Agentic Execution
13. **[`scripts/ai_safety_guardrails.py`](../scripts/ai_safety_guardrails.py):** Implements PII redaction, prompt injection defense, and read-only query enforcement (regex/keyword-based, with separate SQL and Cypher keyword lists and string-literal-aware tokenization). This is the first of two enforcement layers, not the only one: the MCP server's database connections carry their own privilege- and access-mode-level restrictions regardless of what this scan misses — see `mcp_readonly` in [`mcp_server/financial_data_mcp_server.py`](../mcp_server/financial_data_mcp_server.py) and `docs/ARCHITECTURE.md`'s Security Model. The prompt-injection check is still a fixed regex list (paraphrase, other languages, or encoding easily evade it), but a detected match is now actually quarantined (replaced in the payload) via `sanitize_context_payload`/`quarantine_injection_matches`, not just flagged in metadata — treat detection itself as a coarse filter, not a guarantee, but what it *does* detect no longer reaches an LLM unchanged. PII redaction has two paths: `redact_pii` (blanket value-shape regexes over free text, label-anchored for DOB/passport/national-ID/tax-ID to cut false positives, IBAN checked before the credit-card pattern to avoid a spaced IBAN being partially leaked/mislabeled, returned mapping now holds only a category label never the original value) and `redact_row`/`redact_rows` (field-aware, by real column name against `scripts/_pii_classification.py`'s shared patterns — used by the MCP tools below and recursively inside `sanitize_context_payload`).
13b. **[`scripts/_pii_classification.py`](../scripts/_pii_classification.py):** Single shared source of truth for "what counts as PII" (`PII_PERSONAL_PATTERNS`/`PII_SPECIAL_PATTERNS`/`PII_CUBEJS_MASK_PATTERNS`), consumed by the catalog auto-tagger, the guardrails module above, and Cube.js's dimension masking (`cube/cube.js`'s `queryRewrite`) — previously three independent, drifted opinions.
14. **[`scripts/llmops_telemetry.py`](../scripts/llmops_telemetry.py):** Tracks per-call latencies, token accounting, and model cost estimates as structured JSON trace spans, as real `prometheus_client` Counters/Histograms served by `mcp_sidecar` itself (no separate metrics-exporter process — see [Known Issues](#5-known-issues) for why one used to exist and was removed), and as real OTel spans (one per RAG tier, nested under the calling tool's span) exported via [`scripts/_otel_tracing.py`](../scripts/_otel_tracing.py) to `otel_collector` -> `tempo`.
15. **[`scripts/ollama_agentic_tool_runner.py`](../scripts/ollama_agentic_tool_runner.py):** Native tool-calling runner allowing a local Ollama model (default `gemma4:latest`) to execute FastMCP tools autonomously.
16. **[`mcp_server/financial_data_mcp_server.py`](../mcp_server/financial_data_mcp_server.py):** FastMCP server exposing 6 tools (`search_data_catalog`, `query_semantic_metrics`, `query_knowledge_graph`, `query_financial_database`, `check_data_quality`, `hybrid_rag_search`).

### E. Evaluation, Web UI & Benchmarks
17. **[`scripts/rag_triad_evaluator.py`](../scripts/rag_triad_evaluator.py):** Heuristic (token-overlap) scorer for Context Relevance, Faithfulness, and Answer Relevance. Now the *fallback* scorer, used only when the LLM judge (below) is unavailable — on its own, treat its scores as pass/fail sanity checks, not as accuracy or hallucination measurements, since it has no model in the loop.
17b. **[`scripts/llm_judge_evaluator.py`](../scripts/llm_judge_evaluator.py):** Real semantic RAG-Triad scoring via the local `gemma4:latest` Ollama model, replacing #17 as the primary scorer whenever Ollama is reachable and the model is pulled (checked once via `is_available()`). Fails open, not closed — an unavailable judge falls back to #17 rather than aborting the benchmark. Empty responses are scored 0 via a deterministic code-level short-circuit rather than a prompt instruction — verified live that the model itself doesn't reliably self-correct on that degenerate case when merely asked to.
18. **[`scripts/evaluate_agentic_retrieval.py`](../scripts/evaluate_agentic_retrieval.py):** 5-scenario smoke-test suite that checks each subsystem responds without error, plus the RAG Triad scores above (LLM judge first, substring fallback second, via its own `score_triad()` method). Not an accuracy benchmark for the same reason as #17.
19. **[`scripts/rag_explorer_dashboard.py`](../scripts/rag_explorer_dashboard.py):** Interactive 6-Tab Streamlit Web Dashboard (`http://localhost:8501`).

---

## 3. Official Open-Source Documentation References

- **BIAN (Banking Industry Architecture Network):** [https://bian.org/architectural-framework/](https://bian.org/architectural-framework/)
- **EDM Council FIBO (Financial Industry Business Ontology):** [https://spec.edmcouncil.org/fibo/](https://spec.edmcouncil.org/fibo/)
- **pgvector (PostgreSQL Vector Similarity Search):** [https://github.com/pgvector/pgvector](https://github.com/pgvector/pgvector)
- **Neo4j Cypher Manual:** [https://neo4j.com/docs/cypher-manual/current/](https://neo4j.com/docs/cypher-manual/current/)
- **Cube.js Open-Source Semantic Layer:** [https://cube.dev/docs/](https://cube.dev/docs/)
- **OpenMetadata Enterprise Catalog (1.3.x):** [https://docs.open-metadata.org/](https://docs.open-metadata.org/)
- **Model Context Protocol Python SDK** (provides `mcp.server.fastmcp.FastMCP`, used throughout `mcp_server/`; pinned `mcp>=1.0.0,<2.0.0` per Q11 in the hardening plan — see `CLAUDE.md`): [https://github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)
- **Ollama Models & Tool Calling:** [https://ollama.com/library/gemma4](https://ollama.com/library/gemma4)
- **Prometheus Time-Series Engine:** [https://prometheus.io/docs/introduction/overview/](https://prometheus.io/docs/introduction/overview/)
- **Grafana Documentation:** [https://grafana.com/docs/grafana/latest/](https://grafana.com/docs/grafana/latest/)
- **Streamlit Documentation:** [https://docs.streamlit.io/](https://docs.streamlit.io/)

---

## 4. Developer Operations & Troubleshooting Runbook

### Daily Developer Workflow Commands

1. **Start the database, then verify all active Docker containers:**
   ```bash
   npm run supabase:start   # first time only; use supabase:db:reset to re-seed
   docker compose up -d
   docker compose ps
   ```

2. **Run Syntax & Compilation Check Across All Scripts:**
   ```bash
   python3 -m py_compile scripts/*.py mcp_server/*.py
   ```

3. **Execute Full Agentic Benchmark & RAG Triad Suite:**
   ```bash
   python3 scripts/evaluate_agentic_retrieval.py
   ```

4. **Test FastMCP Tool Handlers:**
   ```bash
   python3 -m mcp_server.test_mcp_server
   ```

5. **Run the pytest Suite** (negative security tests, auth middleware, contract/schema drift check):
   ```bash
   python3 -m pytest tests/ -v
   ```
   Most tests are self-contained (no live stack needed — this is what CI runs). Two files
   (`test_postgres_readonly_role.py`, `test_schema_dbml_drift.py`) additionally run live checks
   against the `mcp_readonly` role / the DB-introspected schema when a database is reachable, and
   skip cleanly (not fail) otherwise.

6. **Test Autonomous Ollama Gemma 4 Function Calling:**
   ```bash
   python3 scripts/ollama_agentic_tool_runner.py
   ```

7. **Launch Streamlit Web UI:**
   ```bash
   streamlit run scripts/rag_explorer_dashboard.py
   ```

8. **Run the Data Pipeline via Dagster** (real asset graph — dependencies, retries, backfill, run
   history — instead of the hand-run sequence above):
   ```bash
   pip install -r orchestration/requirements.txt
   export DAGSTER_HOME="$(pwd)/orchestration/.dagster_home" && mkdir -p "$DAGSTER_HOME"
   dagster dev -f orchestration/definitions.py -p 3001   # UI at http://127.0.0.1:3001
   ```
   See [`orchestration/README.md`](../orchestration/README.md) for the full design rationale
   (including the one non-obvious dependency edge the hand-run sequence's prose ordering never made
   explicit: `lineage_dag` must run *after* `knowledge_graph`'s graph wipe, not before, or its writes
   get lost on the next rebuild) and `scripts/bootstrap_platform.sh` for the simpler,
   dependency-free equivalent that's still the right choice for a first-time or CI-style bring-up.

### Troubleshooting Guide

- **Problem:** `connection refused` on port 8000 or 8001.
  - **Solution:** Both ports are served by the same container — restart via `docker compose restart mcp_sidecar`.
- **Problem:** Neo4j Cypher query error.
  - **Solution:** Ensure `NEO4J_PASSWORD` is configured in `.env` or check container state with `docker ps --filter "name=neo4j"`.
- **Problem:** Grafana dashboard panels show "No Data".
  - **Cause:** Since metrics now come from real MCP tool calls (not a simulator), "No Data" can mean exactly what it says — nothing has called the platform yet.
  - **Solution:** Confirm `mcp_agentic_sidecar` is running and Prometheus's target is up (`curl http://127.0.0.1:9090/api/v1/targets`), then make a real tool call (e.g. `python3 -m mcp_server.test_mcp_server`, or any query through an MCP client) and set Grafana's time range to "Last 5 minutes" with 5s auto-refresh.
- **Problem:** `openmetadata_server` crash-loops with `java.sql.SQLException: Access denied for user 'openmetadata_user'` even though the password in `.env` is correct and verified working against MySQL directly (`docker exec openmetadata_mysql mysql -u openmetadata_user -p...`).
  - **Cause:** `openmetadata_server`'s own config template ([`/opt/openmetadata/conf/openmetadata.yaml`](https://github.com/open-metadata/OpenMetadata) inside the image) reads the env var `DB_USER_PASSWORD`, not `DB_PASSWORD`. If only `DB_PASSWORD` is set, it silently falls back to the image's own hardcoded default (`openmetadata_password`) regardless of what's actually in MySQL. `docker-compose.yml` sets `DB_USER_PASSWORD` correctly as of this fix — if you see this error again, check that env var name first before assuming the credential itself is wrong.
  - **Solution:** Confirm `docker-compose.yml`'s `openmetadata_server` service sets `DB_USER_PASSWORD=${OPENMETADATA_MYSQL_PASSWORD}`.
- **Problem:** After changing `OPENMETADATA_MYSQL_PASSWORD` (or any fresh `openmetadata_db` init), `openmetadata_server` logs `Table 'openmetadata_db.DATABASE_CHANGE_LOG' doesn't exist`.
  - **Cause:** The schema hasn't been migrated into the (new) database yet — this is expected right after `catalog/mysql-data` is wiped or first created.
  - **Solution:** `docker compose run --rm --no-deps --entrypoint /opt/openmetadata/bootstrap/bootstrap_storage.sh openmetadata_server migrate-all`, then `docker compose up -d openmetadata_server`.
- **Problem:** `query_semantic_metrics` / Cube.js Playground return `{"error":"Unauthorized: missing or invalid Cube.js API token."}`.
  - **Cause:** Expected — `cube/cube.js`'s `checkAuth` now rejects any request without a valid `Authorization: Bearer ${CUBEJS_API_SECRET}` header (previously it accepted everything unconditionally). Any caller, including `mcp_server`'s `query_semantic_metrics`, must send that header.
  - **Solution:** Ensure `CUBEJS_API_SECRET` is set in `.env` and passed through to both the `cube` and `mcp_sidecar` services in `docker-compose.yml`.
- **Problem:** Calling the MCP SSE endpoint (`:8001/sse`) returns `401 {"error":"Unauthorized"}`.
  - **Cause:** Expected — the sidecar requires a bearer token matching `MCP_API_KEY` on every request.
  - **Solution:** Send `Authorization: Bearer ${MCP_API_KEY}` with every request to the SSE endpoint.
- **Problem:** `mcp_sidecar` exits immediately with `MCP_API_KEY is not set. Refusing to start the SSE
  endpoint unauthenticated`.
  - **Cause:** Intentional — in SSE mode the server fails closed rather than falling back to running
  unauthenticated.
  - **Solution:** Set `MCP_API_KEY` in `.env` (a long random value), or run with `MCP_TRANSPORT=stdio`
  if you don't need the network endpoint.
- **Problem:** `query_financial_database` / `hybrid_rag_search`'s SQL tier return a connection or
  authentication error even though `POSTGRES_PASSWORD` is set correctly.
  - **Cause:** These connect as the `mcp_readonly` role, configured via a separate pair of variables —
  see step 0 in [section 2](#2-script-by-script-codebase-deep-dive).
  - **Solution:** Set `MCP_PG_READONLY_PASSWORD` in `.env` and run `python3 scripts/configure_readonly_role.py`.

---

## 5. Known Issues

Operational quirks worth knowing before you conclude something in your own setup is broken:

- **`hybrid_rag_search` fails closed by default in `mcp_sidecar`.** The image doesn't install
  `sentence-transformers`/`torch` (a multi-GB build-time/size cost not taken on by default), and the
  vector/re-ranking tiers now refuse to run rather than silently substitute a non-semantic
  approximation. If you need this tool working inside the container, either install those packages in
  `mcp_server/Dockerfile.mcp`, or set `ALLOW_DEGRADED_EMBEDDINGS=1` in `.env` to explicitly accept
  degraded (clearly-tagged) retrieval instead. Running `scripts/hybrid_rag_retriever.py` directly on
  the host works normally if `sentence-transformers`/`torch` are installed there (`pip install -r
  requirements.txt`). See `scripts/_embedding_backend.py`.
- **H1: `CUBEJS_DEV_MODE` is now `false` (production mode), with a real 2-role authorization model —
  no longer an accepted limitation, fixed on explicit request.** A standalone `cubestore` service
  (`cubejs/cubestore:v1.7.17`, single-instance — the same single-operator local-PoC scale tradeoff
  already accepted throughout this platform) gives production mode a real cache/queue driver
  (`CUBEJS_CUBESTORE_HOST`/`PORT`); `cube` also runs as its own refresh worker
  (`CUBEJS_REFRESH_WORKER=true`), which production mode needs to actually build `pre_aggregations`
  rollups (dev mode did this implicitly on first query; production mode does not without a refresh
  worker — a real, live-discovered gap, not assumed). `checkAuth` in `cube/cube.js` now compares
  bearer tokens with `crypto.timingSafeEqual` instead of `!==`, and recognizes **two** real,
  independently-issued tokens: `CUBEJS_API_SECRET` (privileged — full access) and
  `CUBEJS_API_SECRET_RESTRICTED` (restricted — general BIAN/FIBO access only). `queryRewrite`'s
  `AML_RESTRICTED_MEMBERS` set enforces the boundary: AML risk classification fields
  (`party_role_customer.aml_risk_rating`/`high_aml_risk_count`/`high_aml_risk_ratio`,
  `ref_country.is_high_risk_aml`/`high_risk_aml_country_count`,
  `ref_nace_industry.risk_level`/`high_risk_industry_count`) require the privileged role — real
  compliance-sensitive data, not an invented tenant dimension. A genuine bug caught live while
  verifying this: `collectReferencedMembers` (H2's PII-masking helper, reused here) only walked
  `dimensions`/`timeDimensions`/`filters`, never `measures` — an AML-restricted *measure* queried via
  `{"measures": [...]}` alone sailed straight through the check unblocked until fixed. Cube.js also
  now connects to Postgres as the least-privilege `cube_readonly` role (see
  `supabase/migrations/20260808150000_create_cube_readonly_role.sql`) instead of the `postgres`
  superuser — a deliberate sibling of `mcp_readonly`, not a shared login. Configure both roles'
  passwords with `python3 scripts/configure_readonly_role.py`.
- **H2: `public: false` on a Cube.js dimension does not, by itself, block a REST query against it in
  this Cube.js version.** Verified live by reading `api-gateway`'s own source: `cube.public === false`
  is checked only in `graphql.js` (GraphQL schema generation), never in the REST `/load` query path. A
  dimension marked `public: false` in `cube/model/cubes/*.yml` still needs a matching entry in
  `cube/cube.js`'s `MASKED_PII_MEMBERS` (the real enforcement, via `queryRewrite`) or it's just hidden
  from the Playground/GraphQL schema while still directly queryable. `tests/test_pii_cube_enforcement.py`
  cross-checks the two lists stay in sync; if you add a new special-category PII dimension, both the
  YAML `public: false` flag and the `cube.js` entry are required.
- **The Neo4j `apoc` plugin was removed** (nothing in this repo called any APOC procedure, and it was
  previously configured with every procedure unrestricted — an SSRF/file-access surface for no
  benefit). If a script genuinely needs a specific APOC procedure in the future, re-add the plugin with
  `NEO4J_dbms_security_procedures_allowlist=apoc.<specific.procedure>` naming only that procedure.
- **Neo4j Community Edition (this platform's `neo4j:5.18.0-community` image) has no custom-role
  RBAC** — there's no way to create a Postgres-`mcp_readonly`-equivalent restricted database user for
  Neo4j. `query_neo4j()` instead opens sessions with `default_access_mode=READ_ACCESS`, which the
  server enforces by rejecting write clauses (verified live: `CREATE`/`SET` both raise
  `Neo.ClientError.Statement.AccessMode` inside such a session) — this holds regardless of the
  Cypher keyword guardrail, but note it does *not* block a non-write procedure call (e.g. an APOC
  HTTP-fetch procedure used for SSRF), which is why the guardrail's Cypher keyword list still blocks
  `CALL` and the plugin itself was removed rather than merely restricted.

- **~~Five services still run on `network_mode: "host"`~~ — fixed 2026-08-08 (H4).** All 13 services
  that were on host mode now join a bridge network, `platform_network`, with explicit
  `127.0.0.1:<port>:<port>` publishing. See `CLAUDE.md`'s "Docker networking" section for the full
  writeup. MySQL, OpenSearch, and `openmetadata_server` (via `OPENMETADATA_HOST`, same
  secure-by-default pattern as `MCP_HOST`) were already bridge-networked and loopback-only before
  this migration and are unaffected by it.
- **Grafana's own datasource health-check UI can report a false negative for Tempo/Alertmanager**
  (`"Unable to load datasource metadata"` / `"Plugin unavailable"`, both HTTP 500) immediately after
  a container recreate, even though the underlying connectivity is genuinely working — verified live
  via `docker exec grafana_observability_dashboard sh -c "wget -qO- http://tempo:3200/status"` and
  `.../alertmanager:9093/-/healthy"` (both succeed with real data), Grafana's own datasource proxy
  endpoints (also succeed with real live data), and Grafana's own server logs showing the failing
  health-check calls complete in 3-5ms — far too fast to be a real network timeout. Not a
  bridge-networking regression (the same Tempo-search-emptiness pattern was observed before the H4
  migration too); treat a red datasource health check as inconclusive and verify via `docker exec` +
  `wget`/the proxy endpoint before assuming a real outage.
- **`schema.dbml` is a generated file** (`python3 scripts/generate_schema_dbml.py`) — do not hand-edit
  it; a migration that changes the schema without regenerating it will show up as drift under
  `--check` (and in `tests/test_schema_dbml_drift.py`, when a live database is reachable).
- **`OPENMETADATA_JWT_TOKEN` unset makes GET requests to `openmetadata_server` crash, not just run
  unauthenticated.** With no token, every request sends `Authorization: Bearer ` (empty token,
  trailing space). PUT/POST calls to most endpoints handle this fine (unauthenticated write, per
  H10's original note); some GET endpoints (e.g. `GET /api/v1/tables`) instead 500 with
  `StringIndexOutOfBoundsException: begin 7, end 6, length 6` — a server-side bug parsing the
  malformed header, not something this repo's code can fix. If you hit this, log in as this
  deployment's default basic-auth admin (`admin@openmetadata.org` / `admin`, from
  `AUTHENTICATION_PROVIDER=basic` with no `ADMIN_PRINCIPALS` override — see
  `docker-compose.yml`'s `openmetadata_server` env) via `POST /api/v1/users/login` to get a
  short-lived session token, or mint a real long-lived bot token through the OpenMetadata UI and set
  `OPENMETADATA_JWT_TOKEN` in `.env` properly. Affects `scripts/sync_end_to_end_lineage.py`'s
  `sync_openmetadata_lineage()` and any MCP tool that calls `search_data_catalog`/
  `check_data_quality` (both degrade to a clean logged error string, not a crash, in that case).
- **`cadvisor`'s per-container metric discovery may not work in every Docker environment.** It logs
  `failed to identify the read-write layer ID` for every real container in some environments (this
  repo's own dev environment among them) and only exposes the aggregate root-cgroup metric
  (`container_memory_usage_bytes{id="/"}`, etc.) in that case — root-caused to `/var/lib/docker` not
  corresponding to the actual dockerd's overlayfs layer metadata as seen from inside the container;
  confirmed not a permissions issue (`--privileged` made no difference). `catalog/prometheus_rules.yml`'s
  container alert is written against the aggregate metric for exactly this reason. On a host where
  cAdvisor's normal discovery works, the same config should populate real per-container series with
  no changes needed. **Accepted limitation for this environment specifically — not planned; do not
  attempt further workarounds (e.g. alternate storage-driver mounts, a different cAdvisor version)
  without an explicit request.**
- **Neo4j Community Edition has no Prometheus/Graphite/JMX metrics reporter at all** — that's an
  Enterprise-only feature (verified live: scanning every jar in the image finds no
  `PrometheusOutput`-style class, and Neo4j's own config validator rejects
  `metrics.prometheus.endpoint` as unrecognized). The `neo4j_jvm` Prometheus target (`:9101`) only
  ever exposes generic `java_lang_*`/`jvm_*`/`process_*` metrics (heap, GC, threads, FDs, CPU) via a
  `jmx_prometheus_javaagent` attached to the JVM's standard JMX endpoint — genuine JVM-health
  alerting, but never transaction rate, page cache hit ratio, or other Neo4j-domain metrics; Community
  registers no custom MBeans for those either. **Accepted limitation — not planned; closing this gap
  would require a paid Neo4j Enterprise license, out of scope under the open-source-only constraint,
  so do not attempt to work around it (e.g. scraping internal APIs, a third-party unofficial exporter)
  without an explicit request.**
- **No backup/restore or disaster-recovery path exists for Postgres, Neo4j, or MySQL** — no scheduled
  dump/snapshot job, no documented restore procedure, and none has ever been tested. Part 5 item 8 of
  the hardening plan names `pgBackRest`/`neo4j-admin dump` on a schedule as the eventual OSS answer.
  **Accepted limitation — not planned; do not implement any backup/restore/DR tooling without an
  explicit request.**

The items above marked "Accepted limitation" are deliberate, out-of-scope trade-offs for this PoC —
not scheduled for remediation, and not to be fixed proactively. Everything else in this section is
tracked for remediation; this section exists so all of it reads as known/expected behavior rather than
new bugs when you hit it.
