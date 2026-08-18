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
network, `platform_network`. Services reach each other via Docker Compose's own service-name DNS
(`neo4j:7687`, `cube:4000`, `prometheus:9090`, ...) rather than `127.0.0.1`; host-facing ports are
published explicitly via `ports:`, each scoped to `127.0.0.1:<port>:<port>` unless a service is meant
to be human-reachable only (see the per-service table below for each one's actual publish address).
**PostgreSQL is the one exception** — it is *not* a `docker-compose.yml` service. It is managed by the
Supabase CLI (`npm run supabase:start`, wrapping `supabase start`), which runs its own Postgres
container (image `supabase/postgres:15.1.0.147`, published on `127.0.0.1:54322`) plus its own scratch
state under `supabase/.temp/`. Start it *before* `docker compose up -d` — the 3 services that need it
(`cube`, `postgres_exporter`, `mcp_sidecar`) reach it via `extra_hosts:
["host.docker.internal:host-gateway"]` (required explicitly on Linux) rather than `127.0.0.1`, and
will crash-loop against a refused connection until Postgres is up. See `CLAUDE.md`'s "Docker
networking" section for the full bridge-network layout, including why every internal bind address is
`0.0.0.0` (safe under bridge networking's own container isolation) with exposure controlled solely by
the `ports:` mapping's host-side address.

### Active Service Inventory

| Container Name | Service Image | Port | Config / Environment Variables | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `openmetadata_mysql` | `mysql:8.0.35` | `3306` (published loopback-only as `127.0.0.1:33060`) | `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD` (both `${OPENMETADATA_MYSQL_PASSWORD}`, no fallback — required) | OpenMetadata catalog backend database |
| `openmetadata_search` | `opensearchproject/opensearch:2.11.0` | `9200` (published loopback-only as `127.0.0.1:9200`) | `DISABLE_SECURITY_PLUGIN=true` | Catalog search index (security plugin off; only reachable from the host or the internal Docker network, never externally) |
| `openmetadata_server` | `openmetadata/server:1.3.1` | `8585` (published loopback-only as `127.0.0.1:8585` unless `OPENMETADATA_HOST` overrides it) | `OPENMETADATA_URL`, `OPENMETADATA_JWT_TOKEN`, `DB_USER_PASSWORD` (⚠️ not `DB_PASSWORD` — see Troubleshooting) | Enterprise Data Catalog UI & REST API |
| `openmetadata_search_reindex` | `python:3.11-slim` (same digest pin as [`mcp_server/Dockerfile.mcp`](../mcp_server/Dockerfile.mcp)) | n/a (long-running watcher, `restart: always`, heartbeat healthcheck) | bind-mounts `scripts/` read-only and runs [`scripts/rebuild_search_index.py`](../scripts/rebuild_search_index.py) `--watch`; `depends_on: openmetadata_server: condition: service_healthy` | Rebuilds `openmetadata_search`'s tmpfs-backed index (see that service's row and its own comment in `docker-compose.yml`) whenever it finds it empty. Deliberately **not** a one-shot init container: `restart: "no"` containers are not relaunched after a host reboot, which live-reproduced as the index staying empty and `search_data_catalog` returning `HTTP 500 index_not_found_exception` again. The `--watch` loop plus `restart: always` is what makes it survive a reboot; the healthcheck is a liveness heartbeat, since a watcher that has exited is indistinguishable from one that is idle. Idempotent. |
| `neo4j_knowledge_graph` | `neo4j:5.18.0-community` | `7474` / `7687`, plus `9101` (bound `127.0.0.1`, JVM-only Prometheus metrics — Neo4j Community has no native reporter, this is a `jmx_prometheus_javaagent` attached in-process via `NEO4J_server_jvm_additional`) | `NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}` (no fallback — required) | Knowledge Graph database & Bolt driver |
| `cube_semantic_layer` | `cubejs/cube:v0.35` | `4000` (REST API + Developer Playground), plus `15432` (Cube SQL, bridge-internal only — not published to the host) | `CUBEJS_DB_TYPE=postgres`, `CUBEJS_API_SECRET` / `CUBEJS_API_SECRET_RESTRICTED` — [`cube/cube.js`](../cube/cube.js)'s `checkAuth` rejects any REST/GraphQL request whose `Authorization: Bearer` token doesn't match one of these two secrets, unaffected by dev vs. production mode. `CUBEJS_DEV_MODE=true` — verified live that dev mode unconditionally opens Cube SQL (Postgres wire protocol) on `:15432` regardless of `CUBEJS_SQL_PORT` being unset, and that without `CUBEJS_SQL_USER`/`CUBEJS_SQL_PASSWORD` set, it accepts *any* username/password and serves real (non-PII/non-AML) financial rows with zero credentials to any container on `platform_network`; both are now set, closing that gap — `queryRewrite`'s PII/AML-restricted-member checks apply on this path either way. | Open-Source Semantic Layer, development mode (Playground UI enabled), backed by the standalone `cubestore` service |
| `prometheus_metrics` | `prom/prometheus:v2.51.0` | `9090` | [catalog/prometheus.yml](../catalog/prometheus.yml) | Operational time-series metrics engine |
| `grafana_observability_dashboard` | `grafana/grafana:13.1.3` | `3000` | `GF_SECURITY_ADMIN_PASSWORD` | Visual monitoring dashboard portal |
| `mcp_agentic_sidecar` | [`mcp_server/Dockerfile.mcp`](../mcp_server/Dockerfile.mcp) | `8001` (SSE, bound to `127.0.0.1` unless `MCP_HOST` overrides it) and `8000` (`/metrics`) | `MCP_TRANSPORT=sse`, `MCP_PORT=8001`, `MCP_METRICS_PORT=8000`, `MCP_HOST`, `MCP_API_KEY` — required; the SSE endpoint refuses to start without it, rather than falling back to unauthenticated. Connects to Postgres as `MCP_PG_READONLY_USER`/`MCP_PG_READONLY_PASSWORD` (the `mcp_readonly` role), not the superuser. | FastMCP Server SSE HTTP agent daemon **and** the platform's real Prometheus metrics source (`prometheus_client.start_http_server()`); runs as non-root `appuser` |
| `otel_collector` | `otel/opentelemetry-collector:0.158.0` | `4317` (OTLP/gRPC), `4318` (OTLP/HTTP), `13133` (health, host-side only — see below) | [catalog/otel-collector-config.yaml](../catalog/otel-collector-config.yaml) | Receives real trace spans from `mcp_sidecar`, batches, forwards to `tempo` |
| `tempo_tracing_backend` | `grafana/tempo:3.0.2` | `3200` (query API, used by Grafana's datasource), `4319`/`4320` (OTLP receiver, collector-only — see config comment for why these aren't 4317/4318) | [catalog/tempo.yaml](../catalog/tempo.yaml) | Trace storage + TraceQL query backend (monolithic mode, local filesystem storage) |
| `node_exporter` | `prom/node-exporter:v1.8.2` | `9100` (bound `127.0.0.1`) | mounts `/proc`/`/sys`/`/` read-only | Host OS metrics (CPU, memory, disk, filesystem) |
| `postgres_exporter` | `prometheuscommunity/postgres-exporter:v0.15.0` | `9187` (bound `127.0.0.1`) | `DATA_SOURCE_NAME` built from `MCP_PG_READONLY_USER`/`MCP_PG_READONLY_PASSWORD` — connects as the least-privilege role, not the superuser; `--no-collector.wal` (needs a superuser-only function) | Postgres metrics (`pg_up`, connection counts, etc.) |
| `mysqld_exporter` | `prom/mysqld-exporter:v0.15.1` | `9104` (bound `127.0.0.1`) | generates a `.my.cnf` at container startup from `OPENMETADATA_MYSQL_PASSWORD` (v0.15.x removed `DATA_SOURCE_NAME` env-var support) | MySQL metrics (OpenMetadata's backend DB) |
| `cadvisor` | `gcr.io/cadvisor/cadvisor:v0.49.1` | `8081` (bound `127.0.0.1`) | mounts `/var/run/docker.sock:ro` (see the service's own comment on what `:ro` does and doesn't buy) | Container resource metrics — per-container discovery is environment-dependent, see the service comment; falls back to the aggregate root-cgroup metric where it doesn't work |
| `cubestore` | `cubejs/cubestore:v1.7.17` | none published (bridge-internal only) | also acts as its own refresh worker (`CUBEJS_REFRESH_WORKER=true`) so `pre_aggregations` rollups build | Cube.js's cache/queue driver, required for production mode |
| `neo4j_jmx_agent_init` | `alpine:3.20` | n/a (one-shot, `restart: "no"`) | downloads `jmx_prometheus_javaagent` (pinned version + sha256) into the `jmx_exporter_agent` named volume | Init container only — populates the jar the `neo4j` service's javaagent needs; not a long-running service |
| `alertmanager` | `prom/alertmanager:v0.27.0` | `9093` (bound `127.0.0.1`) | [catalog/alertmanager.yml](../catalog/alertmanager.yml) — receiver is a deliberate no-op (`local-null`), no real notification channel configured | Receives/dedupes alerts fired by `catalog/prometheus_rules.yml`; alerts visible via its own UI/API and a provisioned Grafana datasource |

There is no separate telemetry-exporter service for *metrics* — `mcp_sidecar` serves real per-call
metrics itself, since the process that actually executes tool calls is the only one that can
(Prometheus client objects don't share state across processes). *Traces* do have a two-service
backend (`otel_collector` + `tempo`) because that's genuinely how OTel's reference architecture
separates ingestion/batching from storage/query — see `scripts/_otel_tracing.py`.

Every long-running service except `otel_collector`/`tempo` declares a `healthcheck:` in
`docker-compose.yml` -- both of those images are deliberately minimal/distroless (no shell, wget,
curl, or nc) with no way to express one; `restart: always` is their resilience mechanism instead, and
anything depending on them uses `condition: service_started` rather than `service_healthy`.
`neo4j_jmx_agent_init` is the only one-shot init container (`restart: "no"`), not a long-running
service, so it has no healthcheck either -- `neo4j` gates on it via `condition:
service_completed_successfully`. `openmetadata_search_reindex` looks like a second one but is not: it
runs a `--watch` loop under `restart: always` precisely so a host reboot cannot leave the tmpfs-backed
search index unrebuilt.
`openmetadata_server` gates on `openmetadata_db`/`openmetadata_search`, `mcp_sidecar` gates on
`neo4j`/`cube`, `cube` itself gates on `cubestore`, `grafana` gates on `prometheus` (healthy) and
`tempo` (started), `otel_collector` gates on `tempo` (started), and `mysqld_exporter` gates on
`openmetadata_db` (healthy) — all via `depends_on`. Every service also sets `security_opt:
no-new-privileges:true` and a bounded `logging:` driver; Prometheus, Grafana, Tempo, `cubestore`, and
the Neo4j JMX agent's jar persist to named volumes
(`prometheus_data`/`grafana_data`/`tempo_data`/`cubestore_data`/`jmx_exporter_agent`, plus
`alertmanager_data`) instead of losing all history (or, for the two agent/jar cases, having to
re-download/rebuild) on every recreate; config bind mounts (Cube.js's model/`cube.js`, Prometheus's
config + rules, Grafana's provisioning, `tempo.yaml`, `otel-collector-config.yaml`,
`alertmanager.yml`, `neo4j_jmx_exporter_config.yml`) are `:ro`.

### Web UIs & Human-Reachable Endpoints

Every URL below is bound to `127.0.0.1` only — reachable from this host, not the LAN — per this
repo's networking convention (see `CLAUDE.md`'s "Docker networking" section). Two rows are **not**
started by `docker compose up -d` and need a manual command first, noted in the Auth column.

| Tool | URL | Auth |
| :--- | :--- | :--- |
| Neo4j Browser | http://127.0.0.1:7474 | `neo4j` / `NEO4J_PASSWORD` from `.env` |
| Cube.js Developer Playground | http://127.0.0.1:4000 | none to load the page; running a query still needs `CUBEJS_API_SECRET`/`_RESTRICTED`. Only reachable because `CUBEJS_DEV_MODE=true` — production mode removes this UI entirely (see the `cube_semantic_layer` row above) |
| Grafana | http://127.0.0.1:3000 | `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` from `.env` |
| Prometheus | http://127.0.0.1:9090 | none |
| Alertmanager | http://127.0.0.1:9093 | none |
| cAdvisor | http://127.0.0.1:8081 | none |
| OpenMetadata (data catalog) | http://127.0.0.1:8585 | `admin@openmetadata.org` / `OPENMETADATA_ADMIN_PASSWORD` from `.env` |
| Supabase Studio (Postgres UI) | http://127.0.0.1:54323 | none (local dev) |
| Supabase Inbucket (test-email inbox) | http://127.0.0.1:54324 | none |
| RAG Explorer Dashboard (Streamlit) | http://127.0.0.1:8501 | none — **not started by Docker Compose**; run `streamlit run scripts/rag_explorer_dashboard.py` first (see §4, step 7) |
| Dagster UI (asset graph, run history, logs) | http://127.0.0.1:3001 | none — **not started by Docker Compose**; run `dagster dev -f orchestration/definitions.py -p 3001` first (see §4, step 8) |

**No web UI** (API/metrics/protocol endpoints only, in case one is expected):

- **OpenSearch** (`:9200`) — raw REST API, no OpenSearch Dashboards service in this stack.
- **Tempo** (`:3200`) — query API only; browse traces through Grafana's Tempo datasource instead,
  not standalone.
- **MCP sidecar** (`:8001` SSE, `:8000` metrics) — protocol/metrics endpoints, no UI.
- **Cube SQL** (`:15432`) — Postgres-wire protocol, not HTTP; connect with `psql` or any Postgres
  client using `CUBEJS_SQL_USER`/`CUBEJS_SQL_PASSWORD` from `.env`, not a browser.
- **node/postgres/mysqld exporters** (`:9100`/`:9187`/`:9104`) — raw Prometheus text output, not a UI.
- MySQL (`:33060`), Neo4j Bolt (`:7687`) — wire protocols, no HTTP UI at all.

---

## 2. Script-by-Script Codebase Deep Dive

> **Shortcut:** [`scripts/bootstrap_platform.sh`](../scripts/bootstrap_platform.sh) runs every step
> below in the correct order, once, from an empty checkout — starting Postgres, applying migrations,
> seeding data, starting Docker Compose, configuring the least-privilege role, and running the full
> catalog/embedding pipeline. Everything in this section documents what it does and why; run it
> directly if you just want the platform up.

### A. Data Ingestion & Data Generation

0. **Prerequisite — initialize the database and the least-privilege roles.**
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
   `ingestion-bot`, whose JWT is a time-bounded 90-day credential, not a permanent one. This script is
   idempotent (no-ops unless the current token is missing or within 14 days of expiring), is already
   wired into `scripts/bootstrap_platform.sh`, and also runs on its own daily Dagster schedule
   (`orchestration/definitions.py`'s `bot_token_rotation_daily`) independent of when anyone next runs
   the pipeline — so this is normally self-maintaining, not something to remember to run by hand every
   90 days.
1. **[`scripts/generate_synthetic_data.py`](../scripts/generate_synthetic_data.py):** Generates synthetic BIAN/FIBO aligned records and writes them to `supabase/seed.sql`. Does not connect to PostgreSQL itself — see the prerequisite above for how the file actually gets loaded.
2. **[`scripts/populate_openmetadata_tables.py`](../scripts/populate_openmetadata_tables.py):** Registers database services and table metadata into OpenMetadata via REST API. **Required before steps 4–8** — those all fetch table entities from the catalog and no-op silently if this hasn't run.
3. **[`scripts/build_knowledge_graph.py`](../scripts/build_knowledge_graph.py):** Extracts PostgreSQL relational tables and loads them into Neo4j via Cypher transactions; prints the resulting node/relationship counts at the end of each run (deterministic given the seeded synthetic dataset from `generate_synthetic_data.py`, but re-run it for the current number rather than trusting a number written here). Its schema step (constraints + two full-text indexes) reads from committed DDL at [`neo4j/schema/constraints_and_indexes.cypher`](../neo4j/schema/constraints_and_indexes.cypher) rather than hardcoding Cypher inline — the Neo4j analogue of `supabase/migrations/*.sql`. `party_name_fulltext` (over `Individual`/`Organization` name properties) and `reference_name_fulltext` (over `RefCountry`/`RefCurrency`/`RefIndustry`) let an agent resolve a party or reference entity by free-text name instead of requiring an exact code/ID match, e.g. `CALL db.index.fulltext.queryNodes('party_name_fulltext', 'Schmidt') YIELD node, score ...`.

### B. Governance, Lineage & Quality

Steps 4–7 below are mutually independent — each depends only on step 2 having run, not on each other
or on step 3 — and can run in any order or in parallel.

4. **[`scripts/automate_openmetadata_pii_and_profiling.py`](../scripts/automate_openmetadata_pii_and_profiling.py):** Scans columns for sensitive data and attaches PII tags (`PersonalData.Personal`).
5. **[`scripts/ground_fibo_ontology_uris.py`](../scripts/ground_fibo_ontology_uris.py):** Grounds table entities to W3C FIBO class URIs (e.g. `Party` $\rightarrow$ `https://www.omg.org/spec/Commons/PartiesAndSituations/Party` — defined in a separate OMG "Commons" ontology FIBO itself imports, not under FIBO's own `spec.edmcouncil.org/fibo/ontology/` namespace). Every entry in `FIBO_GROUNDING_MAP` is individually grounded against the real upstream FIBO/OMG source — see the map's own module comment for the per-entry rationale.
6. **[`scripts/register_openmetadata_data_contracts.py`](../scripts/register_openmetadata_data_contracts.py):** Registers 3 formal Data Products & Contracts under `contracts/`, parsing `contracts/*.yaml` as the actual source of truth via the shared `scripts/_contracts.py` rather than a hand-duplicated markdown copy.
7. **[`scripts/execute_openmetadata_data_quality_tests.py`](../scripts/execute_openmetadata_data_quality_tests.py):** Runs 59 automated data quality assertions across 12 of the platform's 19 tables.
8. **[`scripts/sync_end_to_end_lineage.py`](../scripts/sync_end_to_end_lineage.py):** Syncs table-to-cube and table-to-graph lineage nodes in OpenMetadata. Depends on step 2 (table entities to attach lineage to). Parses the real `cube/model/cubes/*.yml` definitions for each `Cube_*` entity's measures/dimensions, and emits real `columnsLineage` (table.column → cube.measure/dimension) wherever a dimension/measure's `sql:` is a bare source-table column reference.

8b. **[`scripts/load_ontology_tbox.py`](../scripts/load_ontology_tbox.py):** Loads
`ontology/financial_platform_ontology.ttl` into Neo4j as a queryable TBox — 10 `owl:Class`,
10 properties and 9 FIBO/BIAN groundings become `:OntologyClass`/`:OntologyProperty`/
`:ExternalConcept` nodes with `SUBCLASS_OF`/`DOMAIN`/`RANGE`/`DEFINED_BY` edges. Bridges to the
layers already in that database: `CLASSIFIES` onto the `:KnowledgeEntityType` nodes step 8 creates
— which reuses that step's existing edges rather than re-encoding the same associations, so the full
path is `(:OntologyClass)-[:CLASSIFIES]->(:KnowledgeEntityType)<-[:INSTANTIATES_GRAPH]-(:SemanticCube)
<-[:DERIVES_SEMANTICS_TO]-(:PostgreSQLTable)` — and `INSTANCE_OF` from the ABox to its **most
specific** class. That last word matters when querying: `fin:Party` has *zero* direct `INSTANCE_OF`
edges, because all 1,000 parties are typed as `fin:Individual` (800) or `fin:Organization` (200).
Counting a superclass's instances therefore requires the transitive form —
`(i)-[:INSTANCE_OF]->(:OntologyClass)-[:SUBCLASS_OF*0..]->(c)`, note the `*0..` — which returns the
expected 1,000. This is subsumption as graph reachability, not entailment; nothing infers the edges. Idempotent, about a
second, parsed with `rdflib`.

**Ordering is load-bearing, not a preference.** It must run after *both* step 3
(`build_knowledge_graph.py`) and step 8: `CLASSIFIES` needs step 8's nodes, and `INSTANCE_OF` points
at ABox nodes that step 3 deletes and recreates on every run — so **any graph rebuild leaves the ABox
untyped until this is re-run**. Scoping the reload to `ABOX_LABELS` protects the TBox itself, but no
wipe scope can protect edges into nodes that are legitimately new. The script distinguishes the
expected gap (the `ref_*` lookups have no TBox class) from unexpected untyped nodes and tells you to
re-run; `tests/test_ontology_tbox.py::test_only_reference_data_is_untyped` fails loudly in that state.

### C. Context, Search & Hybrid RAG Retrieval

9. **[`scripts/generate_vector_embeddings.py`](../scripts/generate_vector_embeddings.py):** Generates 384-dimensional dense vectors using `sentence-transformers/all-MiniLM-L6-v2` and indexes them in `pgvector 0.8.0` HNSW. This is genuinely the last step to run — it reads catalog tables (step 2), data products (step 6), and FIBO tags (step 5).
10. **[`scripts/neural_reranker.py`](../scripts/neural_reranker.py):** Uses PyTorch `cross-encoder/ms-marco-MiniLM-L-6-v2` Cross-Encoder to re-rank 1st-stage vector candidates based on deep cross-attention.
11. **[`scripts/text_to_cypher_builder.py`](../scripts/text_to_cypher_builder.py):** Compiles natural language prompts into read-only Neo4j Cypher queries.
12. **[`scripts/hybrid_rag_retriever.py`](../scripts/hybrid_rag_retriever.py):** 5-tier Hybrid RAG orchestrator combining Vector Search + Cypher + Cube.js Metrics + PostgreSQL SQL + TBox-driven query expansion. Tier 5 ([`scripts/_ontology_expansion.py`](../scripts/_ontology_expansion.py)) resolves the prompt to ontology concepts, widens along `SUBCLASS_OF`, and counts rows in the tables those concepts are grounded in. It is **additive**, not a replacement: Tiers 2-4 route on `classify_intent`'s four intents and give better answers where one applies, but a prompt about organizations or loan applications falls through to a generic default — Tier 5 reaches all ten modelled concepts, and gains any concept later added to the TTL with no code change. Concept matching runs in Python against a one-shot fetch of the whole TBox, so no user text is ever bound into a graph query on this path.

### D. Guardrails, Telemetry & Agentic Execution
13. **[`scripts/ai_safety_guardrails.py`](../scripts/ai_safety_guardrails.py):** Implements PII redaction, prompt injection defense, and read-only query enforcement (regex/keyword-based, with separate SQL and Cypher keyword lists and string-literal-aware tokenization). This is the first of two enforcement layers, not the only one: the MCP server's database connections carry their own privilege- and access-mode-level restrictions regardless of what this scan misses — see `mcp_readonly` in [`mcp_server/financial_data_mcp_server.py`](../mcp_server/financial_data_mcp_server.py) and `docs/ARCHITECTURE.md`'s Security Model. The prompt-injection check is a fixed regex list (paraphrase, other languages, or encoding easily evade it), but a detected match is actually quarantined (replaced in the payload) via `sanitize_context_payload`/`quarantine_injection_matches`, not just flagged in metadata — treat detection itself as a coarse filter, not a guarantee, but what it *does* detect no longer reaches an LLM unchanged. PII redaction has two paths: `redact_pii` (blanket value-shape regexes over free text, label-anchored for DOB/passport/national-ID/tax-ID to cut false positives, IBAN checked before the credit-card pattern, returned mapping holds only a category label never the original value) and `redact_row`/`redact_rows` (field-aware, by real column name against `scripts/_pii_classification.py`'s shared patterns — used by the MCP tools below and recursively inside `sanitize_context_payload`).
13b. **[`scripts/_pii_classification.py`](../scripts/_pii_classification.py):** Single shared source of truth for "what counts as PII" (`PII_PERSONAL_PATTERNS`/`PII_SPECIAL_PATTERNS`/`PII_CUBEJS_MASK_PATTERNS`), consumed by the catalog auto-tagger, the guardrails module above, and Cube.js's dimension masking (`cube/cube.js`'s `queryRewrite`).
14. **[`scripts/llmops_telemetry.py`](../scripts/llmops_telemetry.py):** Tracks per-call latencies, token accounting, and model cost estimates as structured JSON trace spans, as real `prometheus_client` Counters/Histograms served by `mcp_sidecar` itself, and as real OTel spans (one per RAG tier, nested under the calling tool's span) exported via [`scripts/_otel_tracing.py`](../scripts/_otel_tracing.py) to `otel_collector` -> `tempo`.
15. **[`scripts/agentic_tool_runner.py`](../scripts/agentic_tool_runner.py):** Native tool-calling runner letting the configured LLM execute FastMCP tools autonomously. The provider comes from `LLM_PROVIDER` in `.env` (`ollama` -> local `gemma4:latest`, `moonshot` -> `moonshotai/Kimi-K2.6`) via [`scripts/_llm_backend.py`](../scripts/_llm_backend.py); nothing in this file branches on provider.
16. **[`mcp_server/financial_data_mcp_server.py`](../mcp_server/financial_data_mcp_server.py):** FastMCP server exposing 7 tools (`search_data_catalog`, `query_semantic_metrics`, `query_knowledge_graph`, `query_ontology`, `query_financial_database`, `check_data_quality`, `hybrid_rag_search`).

### E. Evaluation, Web UI & Benchmarks
17. **[`scripts/rag_triad_evaluator.py`](../scripts/rag_triad_evaluator.py):** Heuristic (token-overlap) scorer for Context Relevance, Faithfulness, and Answer Relevance. The fallback scorer, used only when the LLM judge (below) is unavailable — on its own, treat its scores as pass/fail sanity checks, not as accuracy or hallucination measurements, since it has no model in the loop.
17b. **[`scripts/llm_judge_evaluator.py`](../scripts/llm_judge_evaluator.py):** Real semantic RAG-Triad scoring via whichever model `LLM_PROVIDER` selects, the primary scorer whenever that provider is reachable and the model is available (checked once via `is_available()`). Its result carries `deterministic: false` when the provider refused the `temperature=0.0` it asks for -- `kimi-k2.6` does, so Kimi-scored runs are not reproducible or comparable to Ollama-scored ones. Fails open, not closed — an unavailable judge falls back to #17 rather than aborting the benchmark. Empty responses are scored 0 via a deterministic code-level short-circuit rather than a prompt instruction, since the judge model does not reliably self-correct on that degenerate case when merely asked to.
18. **[`scripts/evaluate_agentic_retrieval.py`](../scripts/evaluate_agentic_retrieval.py):** 5-scenario smoke-test suite that checks each subsystem responds without error, plus the RAG Triad scores above (LLM judge first, substring fallback second, via its own `score_triad()` method). Not an accuracy benchmark for the same reason as #17.
19. **[`scripts/rag_explorer_dashboard.py`](../scripts/rag_explorer_dashboard.py):** Interactive 7-tab Streamlit Web Dashboard (`http://localhost:8501`) — one tab per RAG tier (including Tier 5's ontology expansion, which shows whether a concept was matched in the prompt or reached through `SUBCLASS_OF`), plus a guardrails audit and an LLMOps telemetry tab. The tier tabs render only in RAG Pipeline mode; Autonomous mode drives MCP tools directly and has no equivalent payload.

---

## 3. Official Open-Source Documentation References

- **BIAN (Banking Industry Architecture Network):** [https://bian.org/architectural-framework/](https://bian.org/architectural-framework/)
- **EDM Council FIBO (Financial Industry Business Ontology):** [https://spec.edmcouncil.org/fibo/](https://spec.edmcouncil.org/fibo/)
- **pgvector (PostgreSQL Vector Similarity Search):** [https://github.com/pgvector/pgvector](https://github.com/pgvector/pgvector)
- **Neo4j Cypher Manual:** [https://neo4j.com/docs/cypher-manual/current/](https://neo4j.com/docs/cypher-manual/current/)
- **RDFLib** (parses `ontology/*.ttl` in [`scripts/load_ontology_tbox.py`](../scripts/load_ontology_tbox.py); declared in `requirements.txt`, deliberately *not* in `catalog/requirements.exporter.txt` — the MCP sidecar queries the loaded TBox in Neo4j rather than parsing Turtle): [https://rdflib.readthedocs.io/](https://rdflib.readthedocs.io/)
- **W3C RDF Schema 1.1** (the only vocabulary level this TBox uses — `rdfs:subClassOf`/`domain`/`range`, no OWL construct that would need a reasoner): [https://www.w3.org/TR/rdf-schema/](https://www.w3.org/TR/rdf-schema/)
- **Cube.js Open-Source Semantic Layer:** [https://cube.dev/docs/](https://cube.dev/docs/)
- **OpenMetadata Enterprise Catalog (1.3.x):** [https://docs.open-metadata.org/](https://docs.open-metadata.org/)
- **Model Context Protocol Python SDK** (provides `mcp.server.fastmcp.FastMCP`, used throughout `mcp_server/`; pinned `mcp>=1.0.0,<2.0.0` — see `CLAUDE.md`): [https://github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)
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
   Most tests are self-contained (no live stack needed — this is what CI runs). Five files
   additionally run live checks when a database is reachable and skip cleanly (not fail) otherwise:
   `test_postgres_readonly_role.py` and `test_schema_dbml_drift.py` (the `mcp_readonly` role / the
   DB-introspected schema), and `test_graph_wipe_scope.py`, `test_ontology_tbox.py` and
   `test_ontology_expansion.py` (the Neo4j TBox, its bridges, and the retriever's expansion tier).
   A skipped live test is not a passing one — if you are validating a real deployment rather than a
   diff, run these against the running stack and check the summary reports no skips you did not
   expect.

6. **Test Autonomous Function Calling** (against whichever provider `LLM_PROVIDER` selects):
   ```bash
   python3 scripts/agentic_tool_runner.py

   # Or override for a single run, without editing .env:
   LLM_PROVIDER=moonshot python3 scripts/agentic_tool_runner.py
   ```
   It prints the resolved provider and model, and an availability probe, before doing any work --
   and exits non-zero if the loop fails, rather than reporting success regardless of outcome.

7. **Launch Streamlit Web UI:**
   ```bash
   streamlit run scripts/rag_explorer_dashboard.py
   ```

8. **Run the Data Pipeline via Dagster** — [`orchestration/definitions.py`](../orchestration/definitions.py)
   encodes the same pipeline documented in section 2 above as a real Dagster asset graph, with
   declared dependencies (including the one edge the hand-run sequence's own ordering never makes
   explicit: `ontology_tbox` depends on *both* `knowledge_graph` and `lineage_dag`, because its
   `INSTANCE_OF` edges point at ABox nodes the former recreates and its `CLASSIFIES` edges attach to
   nodes the latter writes — so a `knowledge_graph` rebuild must re-materialize `ontology_tbox` after
   it, which the declared dependency makes automatic), automatic retries, backfill, and persisted run
   history. `knowledge_graph`'s wipe is scoped to `ABOX_LABELS`, so `lineage_dag`'s nodes and the TBox
   are no longer destroyed by a rebuild — only edges *into* the recreated ABox nodes are.
   It runs on the **host**, alongside the other standalone pipeline scripts it orchestrates (not
   containerized) — it reaches Postgres/Neo4j/OpenMetadata/Cube.js at their host-published
   `127.0.0.1:<port>` addresses exactly the way a human running these scripts by hand already does.

   **Setup** (once per checkout):
   ```bash
   pip install -r orchestration/requirements.txt

   # Dagster persists run history/logs/event storage under DAGSTER_HOME -- if unset, it falls back
   # to a temp directory that's wiped on reboot, which would make "run history" illusory. Point it
   # somewhere real and persistent, and add this line to your shell profile (or re-run it in every
   # new shell before using Dagster) -- it's read by Dagster itself, not this platform's own Python
   # code, so it isn't picked up from .env:
   export DAGSTER_HOME="$(pwd)/orchestration/.dagster_home"
   mkdir -p "$DAGSTER_HOME"
   ```

   **Prerequisites** — start PostgreSQL and the Docker Compose stack first, the same prerequisite the
   pipeline scripts already have when run by hand:
   ```bash
   npm run supabase:start
   docker compose up -d
   ```

   **Usage:**
   ```bash
   # Launches the Dagster UI (asset graph, run history, logs) on :3001 -- not the
   # default :3000, which Grafana already uses in this platform.
   dagster dev -f orchestration/definitions.py -p 3001   # UI at http://127.0.0.1:3001
   ```
   Open `http://127.0.0.1:3001`, select the `full_pipeline` job, and click **Materialize all**. Assets
   that share only a common upstream dependency (e.g. `knowledge_graph`, `catalog_tables`, and
   `readonly_role_configured`, which all depend only on `postgres_seeded`) run concurrently —
   parallelism the hand-run shell sequence has no way to express. A failed asset can be retried
   individually (each service-calling asset also carries its own automatic retry policy — 2 retries,
   10s apart, for exactly the transient-connectivity case a fresh `docker compose up -d` often hits)
   without re-running everything before it. Equivalently, from the CLI:
   ```bash
   dagster asset materialize -f orchestration/definitions.py --select '*'
   ```

   **What this does not replace:** `scripts/bootstrap_platform.sh` still exists and still works — it's
   the simpler, dependency-free path for a first-time or CI-style bring-up (no `pip install -r
   orchestration/requirements.txt`, no `DAGSTER_HOME`, no UI to open). This orchestration layer is for
   iterating on the pipeline afterward: re-running one failed step, backfilling after a schema change,
   or watching real run history accumulate across many runs, none of which the shell script provides.

### Troubleshooting Guide

- **Problem:** `connection refused` on port 8000 or 8001.
  - **Solution:** Both ports are served by the same container — restart via `docker compose restart mcp_sidecar`.
- **Problem:** Neo4j Cypher query error.
  - **Solution:** Ensure `NEO4J_PASSWORD` is configured in `.env` or check container state with `docker ps --filter "name=neo4j"`.
- **Problem:** Grafana dashboard panels show "No Data".
  - **Cause:** Metrics come from real MCP tool calls, not a simulator — "No Data" can mean exactly what it says: nothing has called the platform yet.
  - **Solution:** Confirm `mcp_agentic_sidecar` is running and Prometheus's target is up (`curl http://127.0.0.1:9090/api/v1/targets`), then make a real tool call (e.g. `python3 -m mcp_server.test_mcp_server`, or any query through an MCP client) and set Grafana's time range to "Last 5 minutes" with 5s auto-refresh.
- **Problem:** `openmetadata_server` crash-loops with `java.sql.SQLException: Access denied for user 'openmetadata_user'` even though the password in `.env` is correct and verified working against MySQL directly (`docker exec openmetadata_mysql mysql -u openmetadata_user -p...`).
  - **Cause:** `openmetadata_server`'s own config template ([`/opt/openmetadata/conf/openmetadata.yaml`](https://github.com/open-metadata/OpenMetadata) inside the image) reads the env var `DB_USER_PASSWORD`, not `DB_PASSWORD`. If only `DB_PASSWORD` is set, it silently falls back to the image's own hardcoded default (`openmetadata_password`) regardless of what's actually in MySQL.
  - **Solution:** Confirm `docker-compose.yml`'s `openmetadata_server` service sets `DB_USER_PASSWORD=${OPENMETADATA_MYSQL_PASSWORD}`.
- **Problem:** After changing `OPENMETADATA_MYSQL_PASSWORD` (or any fresh `openmetadata_db` init), `openmetadata_server` logs `Table 'openmetadata_db.DATABASE_CHANGE_LOG' doesn't exist`.
  - **Cause:** The schema hasn't been migrated into the (new) database yet — this is expected right after `catalog/mysql-data` is wiped or first created.
  - **Solution:** `docker compose run --rm --no-deps --entrypoint /opt/openmetadata/bootstrap/bootstrap_storage.sh openmetadata_server migrate-all`, then `docker compose up -d openmetadata_server`.
- **Problem:** `query_semantic_metrics` / Cube.js Playground return `{"error":"Unauthorized: missing or invalid Cube.js API token."}`.
  - **Cause:** `cube/cube.js`'s `checkAuth` rejects any request without a valid `Authorization: Bearer` header matching `CUBEJS_API_SECRET` or `CUBEJS_API_SECRET_RESTRICTED`. Any caller, including `mcp_server`'s `query_semantic_metrics`, must send that header.
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
  vector/re-ranking tiers refuse to run rather than silently substitute a non-semantic approximation.
  If you need this tool working inside the container, either install those packages in
  `mcp_server/Dockerfile.mcp`, or set `ALLOW_DEGRADED_EMBEDDINGS=1` in `.env` to explicitly accept
  degraded (clearly-tagged) retrieval instead. Running `scripts/hybrid_rag_retriever.py` directly on
  the host works normally if `sentence-transformers`/`torch` are installed there (`pip install -r
  requirements.txt`). See `scripts/_embedding_backend.py`.
- **`public: false` on a Cube.js dimension does not, by itself, block a REST query against it in this
  Cube.js version.** `cube.public === false` is checked only in `graphql.js` (GraphQL schema
  generation), never in the REST `/load` query path. A dimension marked `public: false` in
  `cube/model/cubes/*.yml` still needs a matching entry in `cube/cube.js`'s `MASKED_PII_MEMBERS` (the
  real enforcement, via `queryRewrite`) or it's just hidden from the Playground/GraphQL schema while
  still directly queryable. `tests/test_pii_cube_enforcement.py` cross-checks the two lists stay in
  sync; if you add a new special-category PII dimension, both the YAML `public: false` flag and the
  `cube.js` entry are required.
- **No Neo4j plugins are installed.** Nothing in this repo calls any APOC procedure, so the plugin
  isn't loaded at all. If a script genuinely needs a specific APOC procedure in the future, add the
  plugin with `NEO4J_dbms_security_procedures_allowlist=apoc.<specific.procedure>` naming only that
  procedure — never an unrestricted wildcard.
- **Neo4j Community Edition (this platform's `neo4j:5.18.0-community` image) has no custom-role
  RBAC** — there's no way to create a Postgres-`mcp_readonly`-equivalent restricted database user for
  Neo4j. `query_neo4j()` instead opens sessions with `default_access_mode=READ_ACCESS`, which the
  server enforces by rejecting write clauses (`CREATE`/`SET` both raise
  `Neo.ClientError.Statement.AccessMode` inside such a session) — this holds regardless of the
  Cypher keyword guardrail, but it does *not* block a non-write procedure call (e.g. an APOC
  HTTP-fetch procedure used for SSRF), which is why the guardrail's Cypher keyword list still blocks
  `CALL` and no APOC plugin is installed at all.
- **`kimi-k2.6` accepts only `temperature=1`.** Any other value returns `HTTP 400 invalid
  temperature: only 1 is allowed for this model`. `scripts/_llm_backend.py` omits the field for
  `kimi-*` models rather than coercing it, and flags the call as
  `temperature_honored: false`. The visible consequence is the RAG-Triad LLM judge: it requests
  `0.0` for reproducible scores and cannot get it under Kimi, so its output carries
  `deterministic: false` and its scores vary between runs. Scores from the two providers are
  therefore not directly comparable. Ollama honors any temperature.
- **A Neo4j graph rebuild leaves the ABox untyped until the TBox loader re-runs.** This is a real
  coupling, not a bug to work around. `scripts/build_knowledge_graph.py` deletes and recreates every
  ABox node on each run; `INSTANCE_OF` edges point *at* those nodes, so they cannot survive — an edge
  into a deleted node is gone by definition. Scoping the wipe to `ABOX_LABELS` protects the TBox nodes
  and the lineage sub-graph beside them, but no wipe scope can protect edges into nodes that are
  legitimately new. Symptom: `query_ontology` still lists every concept, but instance counts read 0
  and the retriever's Tier 5 expansion returns concepts with no rows behind them. Fix: re-run
  `python3 scripts/load_ontology_tbox.py` (idempotent, about a second). Dagster does this
  automatically — `ontology_tbox` declares `deps=[knowledge_graph, lineage_dag]` — so this only bites
  a hand-run rebuild. `tests/test_ontology_tbox.py::test_only_reference_data_is_untyped` fails loudly
  in that state rather than letting it pass silently.
- **Tier 5 ontology expansion is deliberately conservative about what it matches**, so a prompt using
  wording the ontology doesn't model expands to nothing and contributes no context. That is the
  intended failure mode: a concept matches only when *every* token of its name is present, because
  matching on any single token ("account") would fire `DepositAccount`, `DepositBalance` and
  `LoanAgreement` on equally weak evidence and degrade the tier into "probe all tables". Tiers 1-4 are
  unaffected — the tier is additive. Use `query_ontology` with `operation='list'` to see the exact
  vocabulary it matches against.
- **`schema.dbml` is a generated file** (`python3 scripts/generate_schema_dbml.py`) — do not hand-edit
  it; a migration that changes the schema without regenerating it will show up as drift under
  `--check` (and in `tests/test_schema_dbml_drift.py`, when a live database is reachable).
- **`OPENMETADATA_JWT_TOKEN` unset makes GET requests to `openmetadata_server` crash, not just run
  unauthenticated.** With no token, every request sends `Authorization: Bearer ` (empty token,
  trailing space). PUT/POST calls to most endpoints handle this fine (unauthenticated write); some GET
  endpoints (e.g. `GET /api/v1/tables`) instead 500 with `StringIndexOutOfBoundsException: begin 7,
  end 6, length 6` — a server-side bug parsing the malformed header, not something this repo's code
  can fix. If you hit this, run `python3 scripts/rotate_openmetadata_bot_token.py` (needs
  `OPENMETADATA_ADMIN_EMAIL`/`OPENMETADATA_ADMIN_PASSWORD` in `.env`) to mint a real token, or log in
  as this deployment's default basic-auth admin (`admin@openmetadata.org` / `admin`, from
  `AUTHENTICATION_PROVIDER=basic` with no `ADMIN_PRINCIPALS` override — see `docker-compose.yml`'s
  `openmetadata_server` env) via `POST /api/v1/users/login` to get a short-lived session token
  manually. Affects `scripts/sync_end_to_end_lineage.py`'s `sync_openmetadata_lineage()` and any MCP
  tool that calls `search_data_catalog`/`check_data_quality` (both degrade to a clean logged error
  string, not a crash, in that case).
- **`search_data_catalog`/`check_data_quality` can 500 for a second, unrelated reason: a genuinely
  empty search index, not an auth problem.** `openmetadata_search`'s data directory is a tmpfs mount
  by design (see its own `docker-compose.yml` comment), so `table_search_index` doesn't exist at all
  immediately after that container is recreated — `openmetadata_server` returns
  `HTTP 500 index_not_found_exception`, a different error body than the JWT case above but the same
  visible symptom in a calling MCP tool. Live-reproduced: token valid, catalog/MySQL/Postgres data
  fully intact, index simply not yet rebuilt. `openmetadata_search_reindex` (see the service inventory
  above) closes this automatically on every `docker compose up` — this bullet is what to check if you
  ever see the symptom with a **verified-valid** token, e.g. after bypassing that container (running
  `openmetadata_search` standalone, or a manual `docker compose up -d openmetadata_search` without the
  rest of the stack). Manual fix: `python3 scripts/rebuild_search_index.py`.

Deliberately accepted, out-of-scope limitations of this PoC (cAdvisor per-container discovery, Neo4j
Community's absent metrics reporter, backup/restore & DR) are tracked in
[`PLATFORM_ANALYSIS_PLAN.md`](PLATFORM_ANALYSIS_PLAN.md)'s accepted-limitations register, not here.
