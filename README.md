# 🚀 Enterprise AI-Enabled Data Platform

[![CI](https://github.com/edittrich/spike-ai-dataplatform/actions/workflows/ci.yml/badge.svg)](https://github.com/edittrich/spike-ai-dataplatform/actions)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector_0.8.0-336791.svg)](https://github.com/pgvector/pgvector)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.0-008CC1.svg)](https://neo4j.com/)
[![OpenMetadata](https://img.shields.io/badge/OpenMetadata-1.3.1-4B5563.svg)](https://open-metadata.org/)
[![Cube.js](https://img.shields.io/badge/Cube.js-Semantic_Layer-6366F1.svg)](https://cube.dev/)
[![MCP](https://img.shields.io/badge/Model_Context_Protocol-FastMCP-10B981.svg)](https://modelcontextprotocol.io/)
[![License](https://img.shields.io/badge/License-Apache_2.0-green.svg)](LICENSE)

An enterprise-grade, multi-modal **AI-Enabled Data Platform** combining relational 3NF databases, semantic metric layers, W3C FIBO ontologies, Neo4j knowledge graphs, `pgvector` dense vector embeddings, and an **Anthropic FastMCP Server** for autonomous AI Agents.

> 📐 **Architecture & Design:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
> 📖 **Application Runbook:** [`docs/APPLICATION_RUNBOOK.md`](docs/APPLICATION_RUNBOOK.md)

---

## 🏛️ System Architecture

```
+---------------------------------------------------------------------------------------------------+
|                        TIER 6: AI-ENABLED CONSUMPTION & APPLICATIONS                              |
|  [Streamlit Web UI Explorer]   [Autonomous AI Agents]   [Grafana Dashboard]   [SaaS & Apps]        |
+---------------------------------------------------------------------------------------------------+
                                                  ^
                                                  |
+---------------------------------------------------------------------------------------------------+
|                        TIER 5: AGENTIC PROTOCOL & INTERFACE LAYER                                 |
|  [Model Context Protocol (MCP) Server]      [Ollama Autonomous Tool-Calling Runner]               |
+---------------------------------------------------------------------------------------------------+
                                                  ^
                                                  |
+---------------------------------------------------------------------------------------------------+
|                        TIER 4: AI CONTEXT & RETRIEVAL INFRASTRUCTURE                              |
|  [2-Stage Neural Cross-Encoder Re-Ranker]   [Dynamic Text-to-Cypher Builder]   [Hybrid RAG]        |
+---------------------------------------------------------------------------------------------------+
                                                  ^
                                                  |
+---------------------------------------------------------------------------------------------------+
|                        TIER 3: SEMANTIC, KNOWLEDGE & METADATA LAYER                               |
|  [Cube.js Semantic Layer]  [Neo4j Knowledge Graph]  [OpenMetadata Catalog]  [W3C FIBO Grounding]   |
+---------------------------------------------------------------------------------------------------+
                                                  ^
                                                  |
+---------------------------------------------------------------------------------------------------+
|                        TIER 2: MULTI-MODEL STORAGE & COMPUTE DATA PLANE                           |
|  [Supabase PostgreSQL (pgvector)]      [Neo4j Graph Database]      [MySQL Catalog Database]        |
+---------------------------------------------------------------------------------------------------+
                                                  ^
                                                  |
+---------------------------------------------------------------------------------------------------+
|                        TIER 1: DATA INGESTION & INTEGRATION LAYER                                 |
|  [PostgreSQL Seed Pipeline]      [End-to-End Lineage Sync]      [Synthetic Data Generator]         |
+---------------------------------------------------------------------------------------------------+

=====================================================================================================
=== CROSS-CUTTING: AUTH & ACCESS CONTROL   PII REDACTION   PROMPT GUARDRAILS   TELEMETRY & OBSERVABILITY ===
=====================================================================================================
```

This is what's built today. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full
component breakdown, data model, and a clearly-separated roadmap of what's planned but not yet
implemented (CDC ingestion, a lakehouse/warehouse tier, hybrid lexical+vector search, orchestration).

---

## 📦 Capability Cluster Breakdown

### Cluster 1: Metadata, Semantics & Knowledge
- **Enterprise Data Product Catalog (OpenMetadata 1.3.1)**: Governed catalog managing Business Domains (`Party_Customer_Domain`, `Deposit_Liquidity_Domain`, `Loan_Credit_Risk_Domain`), Data Products, and Open Data Contract Standard (ODCS) YAML specs.
- **Automated PII Tagging & Data Quality Profiling**: Automatic classification of sensitive PII fields and continuous execution of 59 automated test assertions (100% Pass).
- **W3C FIBO Ontology Grounding**: Formal URI linkage mapping financial entities directly to W3C FIBO concepts (e.g. `financial.party` $\rightarrow$ `https://spec.edmcouncil.org/fibo/ontology/FND/AgentsAndPeople/Agents/Party`).
- **End-to-End Lineage Sync**: Automated 3-tier DAG lineage tracking (`PostgreSQL` $\rightarrow$ `Cube.js` $\rightarrow$ `Neo4j`).

### Cluster 2: Search, Retrieval, Guardrails & Agentic Tools
- **Vector Search Engine (`pgvector 0.8.0`)**: 384-dimensional dense semantic vector retrieval indexed with HNSW cosine similarity using HuggingFace `sentence-transformers/all-MiniLM-L6-v2`.
- **2nd-Stage Neural Re-Ranking Engine (Cross-Encoder)**: Deep cross-attention re-ranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`) in [scripts/neural_reranker.py](scripts/neural_reranker.py) that re-orders 1st-stage candidates to maximize retrieval precision.
- **Dynamic Text-to-Cypher Knowledge Graph Query Builder**: Natural language to read-only Cypher query compiler in [scripts/text_to_cypher_builder.py](scripts/text_to_cypher_builder.py) supporting entity extraction, relationship traversal, and security validation.
- **Multi-Modal Hybrid RAG Retriever**: Unified 4-tier retrieval engine combining 2-Stage Neural Vector Search + Neo4j Graph-RAG Cypher + Cube.js Semantic Metrics + PostgreSQL Relational SQL.
- **FastMCP Agentic Protocol Sidecar Server (`:8001/sse`)**: Persistent sidecar service in [mcp_server/Dockerfile.mcp](mcp_server/Dockerfile.mcp) exposing 6 agent tools over HTTP/SSE.
- **RAG Triad Smoke-Test Suite**: Heuristic (token-overlap) evaluator in [scripts/rag_triad_evaluator.py](scripts/rag_triad_evaluator.py) scoring Context Relevance, Faithfulness, and Answer Relevance as a fast sanity check — no model is in the loop, so treat scores as pass/fail smoke tests rather than accuracy or hallucination measurements.

### Cluster 3: Master Orchestration & Observability Suite
- **Master Docker Compose Orchestrator**: Unified orchestration in [docker-compose.yml](docker-compose.yml) linking OpenMetadata, Neo4j, Cube.js, Prometheus, Grafana, and the FastMCP Sidecar.
- **Prometheus Metrics Engine (`:9090`)**: Real-time operational metrics scraping engine configured in [catalog/prometheus.yml](catalog/prometheus.yml).
- **Real LLMOps Metrics (`mcp_sidecar:8000/metrics`)**: The MCP sidecar serves genuine `prometheus_client` metrics (tool call counts/outcomes/latency, per-tier retrieval latency, token/cost accounting) directly from the process that executes tool calls — see [scripts/llmops_telemetry.py](scripts/llmops_telemetry.py) and `main()` in [mcp_server/financial_data_mcp_server.py](mcp_server/financial_data_mcp_server.py). There is no separate simulator process.
- **Automated Grafana Dashboard & Datasource Provisioning (`:3000`)**: Zero-touch pre-configured visual dashboard (`http://localhost:3000`, credentials configured via `.env`) provisioned via [catalog/grafana/provisioning](catalog/grafana/provisioning) and [catalog/grafana/dashboards](catalog/grafana/dashboards).
- **Automated GitHub Actions CI/CD**: Workflow in [.github/workflows/ci.yml](.github/workflows/ci.yml) validating syntax, guardrails, telemetry, and MCP tool handlers on `push`/`pull_request` to `main`.

---

## 🛠️ Environment Prerequisites & Quick Start

### 1. Prerequisites
- **Docker & Docker Compose**
- **Python 3.11+**
- **Node.js 18+** (for Cube.js semantic layer)

### 2. Live Platform Services

| Component Service | Local Endpoint / URL | Access Configuration |
| :--- | :--- | :--- |
| **Supabase PostgreSQL (`pgvector`)** | `127.0.0.1:54322` | Configured via `POSTGRES_HOST` / `.env` |
| **Neo4j Knowledge Graph** | `bolt://127.0.0.1:7687` | Configured via `NEO4J_URI` / `.env` |
| **OpenMetadata Catalog UI** | `http://127.0.0.1:8585` | Configured via `OPENMETADATA_URL` / `.env` |
| **Cube.js Semantic Layer REST API** | `http://127.0.0.1:4000` | Configured via `CUBEJS_URL` / `.env` |
| **Local Ollama LLM Engine** | `http://127.0.0.1:11434` | Local model `gemma4:latest` |

---

## 🚀 Execution Guide

### 1. Set Up Environment Variables
```bash
cp .env.example .env
```

### 2. Start PostgreSQL (Supabase CLI) and the Docker Compose Stack
PostgreSQL is managed separately by the Supabase CLI, not by `docker-compose.yml` — start it first,
then the rest of the platform (OpenMetadata Catalog, MySQL, OpenSearch, Neo4j Graph DB, Cube.js
Semantic Engine, Prometheus, Grafana, MCP sidecar):
```bash
npm run supabase:start   # applies migrations to a fresh local Postgres instance
docker compose up -d
```

### 3. Execute Cluster 1: Metadata, Semantics & Governance
```bash
# Generate BIAN/FIBO Synthetic Data as supabase/seed.sql (1,159 Parties, 1,226 Loan Agreements, 1,159 Deposit Balances)
python3 scripts/generate_synthetic_data.py

# Load the generated seed data into PostgreSQL
npm run supabase:db:reset

# Ingest and Seed Neo4j Knowledge Graph
python3 scripts/build_knowledge_graph.py

# Register table metadata into OpenMetadata -- required before the 4 steps below, which all
# fetch table entities from the catalog and no-op silently if this hasn't run yet
python3 scripts/populate_openmetadata_tables.py

# Publish OpenMetadata Domains & ODCS-Inspired Data Product Contracts
python3 scripts/register_openmetadata_data_contracts.py

# Ground Catalog Entities to Official W3C FIBO Ontology Class URIs
python3 scripts/ground_fibo_ontology_uris.py

# Run Automated PII Tagging & Statistical Profiling
python3 scripts/automate_openmetadata_pii_and_profiling.py

# Register and Execute 59 Real-Time Data Quality Assertions
python3 scripts/execute_openmetadata_data_quality_tests.py

# Synchronize 3-Tier Lineage DAGs (PostgreSQL -> Cube.js -> Neo4j)
python3 scripts/sync_end_to_end_lineage.py
```

### 4. Execute Cluster 2: Search, Retrieval, Guardrails & Agentic Tools
```bash
# Generate and Index 60 Dense Vector Embeddings in pgvector (HuggingFace Transformer)
python3 scripts/generate_vector_embeddings.py

# Run Multi-Modal Hybrid RAG Retriever with AI Guardrails & LLMOps Telemetry
python3 scripts/hybrid_rag_retriever.py

# Test Enterprise FastMCP Agentic Tools
python3 -m mcp_server.test_mcp_server

# Run Agentic Evaluation Smoke-Test Suite (5 scenarios; checks each subsystem responds, not answer accuracy)
python3 scripts/evaluate_agentic_retrieval.py

# Execute End-to-End Application Test against Local Ollama Gemma 4
python3 scripts/test_e2e_ollama_pipeline.py

# Run Ollama Gemma 4 Autonomous Function-Calling & Tool Runner
python3 scripts/ollama_agentic_tool_runner.py

# Launch Interactive Streamlit RAG Explorer Web UI Dashboard
streamlit run scripts/rag_explorer_dashboard.py
```

---

## 🔌 Integrating the MCP Server with AI Assistant Clients

To connect our Enterprise FastMCP Server (`mcp_server/financial_data_mcp_server.py`) to AI clients (like Claude Desktop, Antigravity, or Cursor), add the following configuration to your client's `mcpServers` configuration file:

```json
{
  "mcpServers": {
    "financial-data-platform": {
      "command": "python3",
      "args": [
        "/home/edittrich/Documents/workspaces/git/ai-dataplatform/mcp_server/financial_data_mcp_server.py"
      ],
      "env": {
        "OPENMETADATA_URL": "http://127.0.0.1:8585/api/v1",
        "CUBEJS_URL": "http://127.0.0.1:4000/cubejs-api/v1/load",
        "NEO4J_URI": "bolt://127.0.0.1:7687",
        "POSTGRES_HOST": "127.0.0.1"
      }
    }
  }
}
```

---

## 📑 Documentation Index

- [Architecture & Design](docs/ARCHITECTURE.md): system architecture, data model, BIAN/FIBO domain alignment, and roadmap.
- [Application Runbook](docs/APPLICATION_RUNBOOK.md): service inventory, script-by-script deep dive, troubleshooting, known issues.
- [Data Contracts](contracts/): data product contract specs.
- [CLAUDE.md](CLAUDE.md): commands and conventions for agentic coding tools working in this repo.
