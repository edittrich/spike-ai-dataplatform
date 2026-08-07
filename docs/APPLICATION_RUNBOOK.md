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

Most services are orchestrated by [`docker-compose.yml`](../docker-compose.yml), largely in `host`
network mode (`network_mode: "host"`). **PostgreSQL is the one exception** — it is *not* a
`docker-compose.yml` service. It is managed by the Supabase CLI (`npm run supabase:start`, wrapping
`supabase start`), which runs its own Postgres container (image `supabase/postgres:15.1.0.147`,
published on `127.0.0.1:54322`) plus its own scratch state under `supabase/.temp/`. Start it *before*
`docker compose up -d` — `cube` and `mcp_sidecar` both connect to `127.0.0.1:54322` and will crash-loop
against a refused connection until it's up.

### Active Service Inventory

| Container Name | Service Image | Port | Config / Environment Variables | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `openmetadata_mysql` | `mysql:8.0.35` | `3306` (published loopback-only as `127.0.0.1:33060`) | `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD` (both `${OPENMETADATA_MYSQL_PASSWORD}`, no fallback — required) | OpenMetadata catalog backend database |
| `openmetadata_search` | `opensearchproject/opensearch:2.11.0` | `9200` (published loopback-only as `127.0.0.1:9200`) | `DISABLE_SECURITY_PLUGIN=true` | Catalog search index (security plugin off; only reachable from the host or the internal Docker network, never externally) |
| `openmetadata_server` | `openmetadata/server:1.3.1` | `8585` | `OPENMETADATA_URL`, `OPENMETADATA_JWT_TOKEN`, `DB_USER_PASSWORD` (⚠️ not `DB_PASSWORD` — see Troubleshooting) | Enterprise Data Catalog UI & REST API |
| `neo4j_knowledge_graph` | `neo4j:5.18.0-community` | `7474` / `7687` | `NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}` (no fallback — required) | Knowledge Graph database & Bolt driver |
| `cube_semantic_layer` | `cubejs/cube:v0.35` | `4000` | `CUBEJS_DB_TYPE=postgres`, `CUBEJS_API_SECRET` — **enforced**: [`cube/cube.js`](../cube/cube.js)'s `checkAuth` rejects any request whose `Authorization: Bearer` token doesn't match this secret, in both dev and production mode. No `CUBEJS_SQL_PORT` — the Postgres-wire SQL API it would open has no equivalent auth check and nothing uses it. | Open-Source Semantic Layer (REST API) |
| `prometheus_metrics` | `prom/prometheus:v2.51.0` | `9090` | [catalog/prometheus.yml](../catalog/prometheus.yml) | Operational time-series metrics engine |
| `grafana_observability_dashboard` | `grafana/grafana:10.4.0` | `3000` | `GF_SECURITY_ADMIN_PASSWORD` | Visual monitoring dashboard portal |
| `mcp_agentic_sidecar` | [`mcp_server/Dockerfile.mcp`](../mcp_server/Dockerfile.mcp) | `8001` (SSE, bound to `127.0.0.1` unless `MCP_HOST` overrides it) and `8000` (`/metrics`) | `MCP_TRANSPORT=sse`, `MCP_PORT=8001`, `MCP_METRICS_PORT=8000`, `MCP_HOST`, `MCP_API_KEY` — required; the SSE endpoint now **refuses to start** without it, rather than falling back to unauthenticated. Connects to Postgres as `MCP_PG_READONLY_USER`/`MCP_PG_READONLY_PASSWORD` (the `mcp_readonly` role), not the superuser. | FastMCP Server SSE HTTP agent daemon **and** the platform's real Prometheus metrics source (`prometheus_client.start_http_server()`); runs as non-root `appuser` |

There is no separate telemetry-exporter service — `mcp_sidecar` serves real per-call metrics itself
(the process that actually executes tool calls is the only one that can; Prometheus client objects
don't share state across processes, which is exactly why the previous separate exporter container had
to fabricate its data — see [Known Issues](#5-known-issues)).

All services declare a `healthcheck:` in `docker-compose.yml`; `openmetadata_server`'s `depends_on` gates on `openmetadata_db`/`openmetadata_search` reaching `condition: service_healthy` before it starts (fixes a real startup race — see Troubleshooting).

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
   `npm run supabase:db:reset` (re-seed), both defined in [`package.json`](../package.json). This also
   applies `supabase/migrations/20260807151500_create_mcp_readonly_role.sql`, which creates the
   `mcp_readonly` role the MCP server connects as — its password isn't set by the migration itself
   (checked-in files can't hold real secrets), so also run
   `python3 scripts/configure_readonly_role.py` once `MCP_PG_READONLY_PASSWORD` is set in `.env`.
   Skipping any of this leaves later steps running against an empty database, or leaves the MCP server
   unable to authenticate.
1. **[`scripts/generate_synthetic_data.py`](../scripts/generate_synthetic_data.py):** Generates synthetic BIAN/FIBO aligned records and writes them to `supabase/seed.sql`. Does not connect to PostgreSQL itself — see the prerequisite above for how the file actually gets loaded.
2. **[`scripts/populate_openmetadata_tables.py`](../scripts/populate_openmetadata_tables.py):** Registers database services and table metadata into OpenMetadata via REST API. **Required before steps 4–8** — those all fetch table entities from the catalog and no-op silently if this hasn't run.
3. **[`scripts/build_knowledge_graph.py`](../scripts/build_knowledge_graph.py):** Extracts PostgreSQL relational tables and loads them into Neo4j via Cypher transactions; prints the resulting node/relationship counts at the end of each run (deterministic given the seeded synthetic dataset from `generate_synthetic_data.py`, but re-run it for the current number rather than trusting a number written here).

### B. Governance, Lineage & Quality

Steps 4–7 below are mutually independent — each depends only on step 2 having run, not on each other
or on step 3 — and can run in any order or in parallel.

4. **[`scripts/automate_openmetadata_pii_and_profiling.py`](../scripts/automate_openmetadata_pii_and_profiling.py):** Scans columns for sensitive data and attaches PII tags (`PersonalData.Personal`).
5. **[`scripts/ground_fibo_ontology_uris.py`](../scripts/ground_fibo_ontology_uris.py):** Grounds table entities to W3C FIBO class URIs (e.g. `Party` $\rightarrow$ `https://spec.edmcouncil.org/.../Party`).
6. **[`scripts/register_openmetadata_data_contracts.py`](../scripts/register_openmetadata_data_contracts.py):** Registers 3 formal Data Products & Contracts under `contracts/`.
7. **[`scripts/execute_openmetadata_data_quality_tests.py`](../scripts/execute_openmetadata_data_quality_tests.py):** Runs 59 automated data quality assertions across 12 of the platform's 19 tables.
8. **[`scripts/sync_end_to_end_lineage.py`](../scripts/sync_end_to_end_lineage.py):** Syncs table-to-cube and table-to-graph lineage nodes in OpenMetadata. Depends on step 2 (table entities to attach lineage to).

### C. Context, Search & Hybrid RAG Retrieval

9. **[`scripts/generate_vector_embeddings.py`](../scripts/generate_vector_embeddings.py):** Generates 384-dimensional dense vectors using `sentence-transformers/all-MiniLM-L6-v2` and indexes them in `pgvector 0.8.0` HNSW. This is genuinely the last step to run — it reads catalog tables (step 2), data products (step 6), and FIBO tags (step 5).
10. **[`scripts/neural_reranker.py`](../scripts/neural_reranker.py):** Uses PyTorch `cross-encoder/ms-marco-MiniLM-L-6-v2` Cross-Encoder to re-rank 1st-stage vector candidates based on deep cross-attention.
11. **[`scripts/text_to_cypher_builder.py`](../scripts/text_to_cypher_builder.py):** Compiles natural language prompts into read-only Neo4j Cypher queries.
12. **[`scripts/hybrid_rag_retriever.py`](../scripts/hybrid_rag_retriever.py):** 4-tier Hybrid RAG orchestrator combining Vector Search + Cypher + Cube.js Metrics + PostgreSQL SQL.

### D. Guardrails, Telemetry & Agentic Execution
13. **[`scripts/ai_safety_guardrails.py`](../scripts/ai_safety_guardrails.py):** Implements PII redaction, prompt injection defense, and read-only query enforcement (regex/keyword-based, with separate SQL and Cypher keyword lists and string-literal-aware tokenization). This is the first of two enforcement layers, not the only one: the MCP server's database connections carry their own privilege- and access-mode-level restrictions regardless of what this scan misses — see `mcp_readonly` in [`mcp_server/financial_data_mcp_server.py`](../mcp_server/financial_data_mcp_server.py) and `docs/ARCHITECTURE.md`'s Security Model. The prompt-injection check is still a fixed regex list (paraphrase, other languages, or encoding easily evade it) and only warns rather than blocking on a match found in *retrieved* content — treat it as a coarse filter, not a guarantee.
14. **[`scripts/llmops_telemetry.py`](../scripts/llmops_telemetry.py):** Tracks per-call latencies, token accounting, and model cost estimates as structured JSON trace spans (in-process only; not currently wired to an OpenTelemetry exporter).
15. **[`scripts/telemetry_metrics_exporter_server.py`](../scripts/telemetry_metrics_exporter_server.py):** Serves an OpenMetrics payload on port 8000. **Currently a traffic simulator, not a real collector** — see [Known Issues](#5-known-issues).
16. **[`scripts/ollama_agentic_tool_runner.py`](../scripts/ollama_agentic_tool_runner.py):** Native tool-calling runner allowing a local Ollama model (default `gemma4:latest`) to execute FastMCP tools autonomously.
17. **[`mcp_server/financial_data_mcp_server.py`](../mcp_server/financial_data_mcp_server.py):** FastMCP server exposing 6 tools (`search_data_catalog`, `query_semantic_metrics`, `query_knowledge_graph`, `query_financial_database`, `check_data_quality`, `hybrid_rag_search`).

### E. Evaluation, Web UI & Benchmarks
18. **[`scripts/rag_triad_evaluator.py`](../scripts/rag_triad_evaluator.py):** Heuristic (token-overlap) scorer for Context Relevance, Faithfulness, and Answer Relevance. Useful as a fast smoke test; treat its scores as pass/fail sanity checks, not as accuracy or hallucination measurements — it has no model in the loop.
19. **[`scripts/evaluate_agentic_retrieval.py`](../scripts/evaluate_agentic_retrieval.py):** 5-scenario smoke-test suite that checks each subsystem responds without error, plus the RAG Triad scores above. Not an accuracy benchmark for the same reason as #18.
20. **[`scripts/rag_explorer_dashboard.py`](../scripts/rag_explorer_dashboard.py):** Interactive 6-Tab Streamlit Web Dashboard (`http://localhost:8501`).

---

## 3. Official Open-Source Documentation References

- **BIAN (Banking Industry Architecture Network):** [https://bian.org/architectural-framework/](https://bian.org/architectural-framework/)
- **EDM Council FIBO (Financial Industry Business Ontology):** [https://spec.edmcouncil.org/fibo/](https://spec.edmcouncil.org/fibo/)
- **pgvector (PostgreSQL Vector Similarity Search):** [https://github.com/pgvector/pgvector](https://github.com/pgvector/pgvector)
- **Neo4j Cypher Manual:** [https://neo4j.com/docs/cypher-manual/current/](https://neo4j.com/docs/cypher-manual/current/)
- **Cube.js Open-Source Semantic Layer:** [https://cube.dev/docs/](https://cube.dev/docs/)
- **OpenMetadata Enterprise Catalog (1.3.x):** [https://docs.open-metadata.org/](https://docs.open-metadata.org/)
- **Anthropic FastMCP Python SDK:** [https://github.com/jlowin/fastmcp](https://github.com/jlowin/fastmcp)
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

5. **Test Autonomous Ollama Gemma 4 Function Calling:**
   ```bash
   python3 scripts/ollama_agentic_tool_runner.py
   ```

6. **Launch Streamlit Web UI:**
   ```bash
   streamlit run scripts/rag_explorer_dashboard.py
   ```

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
- **`CUBEJS_DEV_MODE` is still `true`.** Disabling it is the right long-term move (dev mode serves the
  Developer Playground and loosens some defaults on a `network_mode: host` port), but production mode
  requires a Cube Store service for its cache/queue driver that isn't deployed in this compose file —
  flipping the flag alone breaks every query (`CUBEJS_CUBESTORE_HOST`/`PORT` not set). `checkAuth` in
  `cube/cube.js` is enforced in both modes (verified live), so authentication itself isn't weaker in
  dev mode — only the Playground/relaxed-defaults surface is. Add a Cube Store service before flipping this.
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

These are tracked for remediation; this section exists so they read as known behavior rather than
new bugs when you hit them.
