#!/usr/bin/env python3
"""
===============================================================================
Multi-Modal Hybrid RAG Retriever (Vector + Graph + Semantic + Relational)
===============================================================================
Unifies 4 retrieval tiers to construct rich context payloads for LLMs:
1. Vector Search (pgvector + HuggingFace sentence-transformers/all-MiniLM-L6-v2)
2. Knowledge Graph Traversal (Neo4j Cypher Multi-Hop Graph-RAG)
3. Semantic Layer Metric Engine (Cube.js REST API)
4. Relational Database SQL Execution (Supabase PostgreSQL)
5. AI Safety & Real-Time Prompt Guardrails (PII Masking & Injection Defense)
6. LLMOps Telemetry & Observability (Token Accounting, Tier Latencies & Trace Spans)
===============================================================================
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import logging
import urllib.request
import urllib.parse
import urllib.error
import time

import psycopg2
from neo4j import READ_ACCESS, GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("HybridRAGRetriever")

from scripts._dotenv_boot import load_env
from scripts._json_safe import json_safe_row
from scripts.ai_safety_guardrails import AISafetyGuardrails

# Loads .env when this module runs on the host (both directly, per CLAUDE.md's
# pipeline docs, and indirectly via the hybrid_rag_search MCP tool's stdio
# case). A no-op inside mcp_sidecar, where docker-compose.yml already injects
# real env vars and `override=False` never replaces them.
load_env()
from scripts.llmops_telemetry import LLMOpsTelemetry
from scripts.neural_reranker import NeuralReranker
from scripts.text_to_cypher_builder import TextToCypherBuilder

# Fails closed by default (raises) if the real sentence-transformers model
# can't load -- set ALLOW_DEGRADED_EMBEDDINGS=1 to accept a non-semantic
# fallback instead. See scripts/_embedding_backend.py for why this used to be
# a silent per-file fallback and what was wrong with that. EMBEDDING_MODE is
# threaded into hybrid_retrieve()'s response payload below so a degraded
# result can never look identical to a real one.
from scripts._embedding_backend import load_embedding_model
get_embedding, EMBEDDING_MODE = load_embedding_model()

CUBEJS_URL = os.getenv("CUBEJS_URL", "http://127.0.0.1:4000/cubejs-api/v1/load")
CUBEJS_API_SECRET = os.getenv("CUBEJS_API_SECRET", "")

# Native driver connection settings, replacing `docker exec <container>
# psql/cypher-shell`, which only works when this process has the `docker`
# CLI and a mounted docker.sock -- neither is true when this class is
# instantiated inside the mcp_sidecar container (via the hybrid_rag_search
# MCP tool), so every call failed with a FileNotFoundError over the real
# SSE endpoint despite passing when run directly on the host.
#
# Connects as `mcp_readonly` (supabase/migrations/20260807151500_create_mcp_readonly_role.sql),
# not the `postgres` superuser -- see the matching comment in
# mcp_server/financial_data_mcp_server.py for why. Configure its password via
# `python3 scripts/configure_readonly_role.py`.
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "54322"))
POSTGRES_USER = os.getenv("MCP_PG_READONLY_USER", "mcp_readonly")
POSTGRES_PASSWORD = os.getenv("MCP_PG_READONLY_PASSWORD", "")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

class HybridRAGRetriever:
    def __init__(self):
        self.guardrails = AISafetyGuardrails()
        self.telemetry = LLMOpsTelemetry()
        self.reranker = NeuralReranker()
        self.cypher_builder = TextToCypherBuilder()
        # Connections are created lazily on first use and reused for the
        # life of this instance, instead of opening a fresh psycopg2
        # connection / constructing an entirely new neo4j.GraphDatabase.driver
        # (which does its own internal connection pooling + routing-table
        # discovery) on every single query_pg/query_neo4j call -- exactly the
        # "connection churn per call" Q6 flagged. The neo4j driver in
        # particular is documented upstream as meant to be built once and
        # reused for an application's lifetime, not per query -- see
        # get_neo4j_driver() below and mcp_server's module-level singleton.
        self._pg_conn = None
        self._neo4j_driver = None

    def _get_pg_conn(self):
        if self._pg_conn is None or self._pg_conn.closed:
            self._pg_conn = psycopg2.connect(
                host=POSTGRES_HOST, port=POSTGRES_PORT, user=POSTGRES_USER,
                password=POSTGRES_PASSWORD, dbname=POSTGRES_DB, connect_timeout=10,
                options="-c statement_timeout=10000 -c idle_in_transaction_session_timeout=30000",
            )
            # Defense in depth: even if a mutation slipped past the keyword
            # check in query_pg, the database itself now refuses to execute
            # it. autocommit=True so each cursor.execute() commits its own
            # implicit transaction immediately -- necessary now that the
            # connection is reused across calls, so one query never leaves
            # an idle transaction open for the next.
            self._pg_conn.set_session(readonly=True, autocommit=True)
        return self._pg_conn

    def _get_neo4j_driver(self):
        if self._neo4j_driver is None:
            self._neo4j_driver = GraphDatabase.driver(
                NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD), connection_timeout=10
            )
        return self._neo4j_driver

    def close(self):
        """Releases this instance's pooled connections. Optional to call --
        the OS reclaims the sockets at process exit regardless -- but worth
        calling explicitly if constructing many short-lived retriever
        instances in a loop rather than one long-lived instance."""
        if self._pg_conn is not None and not self._pg_conn.closed:
            self._pg_conn.close()
        if self._neo4j_driver is not None:
            self._neo4j_driver.close()
            self._neo4j_driver = None

    def query_pg(self, sql, params=None):
        """Returns list[dict] (one dict per row, keyed by column name) --
        not the pipe-delimited text the previous version reconstructed
        purely to keep vector_semantic_search()/relational_sql_search()'s
        brittle `.split("|")` parser working (see Q2: any content_text
        containing a literal `|` shifted columns and raised ValueError)."""
        # Validate read-only SQL safety
        safe, reason = self.guardrails.validate_read_only_query(sql, "SQL")
        if not safe:
            raise ValueError(reason)
        conn = self._get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description is None:
                return []
            columns = [desc[0] for desc in cur.description]
            return [json_safe_row(dict(zip(columns, row))) for row in cur.fetchall()]

    def query_neo4j(self, cypher, params=None):
        """Returns list[dict] -- one dict per record, keyed by the Cypher
        query's own RETURN aliases (via neo4j's record.data())."""
        # Validate read-only Cypher safety
        safe, reason = self.guardrails.validate_read_only_query(cypher, "Cypher")
        if not safe:
            raise ValueError(reason)
        driver = self._get_neo4j_driver()
        # See the matching comment in mcp_server/financial_data_mcp_server.py's
        # query_neo4j: READ_ACCESS is the enforcement available on Neo4j
        # Community Edition in place of a dedicated read-only role/RBAC.
        with driver.session(default_access_mode=READ_ACCESS) as session:
            result = session.run(cypher, params or {})
            return [json_safe_row(record.data()) for record in result]

    def vector_semantic_search(self, prompt, top_k=3, fetch_candidates_k=10):
        """
        Tier 1: 2-Stage Retrieval Pipeline:
        - 1st-Stage: pgvector 0.8.0 HNSW cosine similarity search (fetches candidate_k=10).
        - 2nd-Stage: Neural Cross-Encoder Re-Ranking (ms-marco-MiniLM-L-6-v2) returns top_k=3.
        """
        query_vec = get_embedding(prompt)
        vec_str = "[" + ",".join(str(x) for x in query_vec) + "]"

        # %(vec)s::vector bound as a parameter rather than f-string
        # interpolated -- query_vec is our own computed embedding, not raw
        # user text, so this was never an injection risk the way the C6
        # scripts were, but parameterizing is free here and keeps every
        # query_pg call site in this codebase to the same convention.
        sql = """
        SELECT
            entity_type,
            display_name,
            ROUND((1 - (embedding <=> %(vec)s::vector))::numeric, 4) AS similarity,
            content_text,
            metadata
        FROM financial.entity_embeddings
        ORDER BY embedding <=> %(vec)s::vector ASC
        LIMIT %(k)s;
        """
        rows = self.query_pg(sql, {"vec": vec_str, "k": fetch_candidates_k})
        candidates = [
            {
                "entity_type": row["entity_type"],
                "display_name": row["display_name"],
                "similarity": float(row["similarity"]),
                "content_text": row["content_text"],
            }
            for row in rows
        ]

        # Apply 2nd-stage Cross-Encoder neural re-ranking
        reranked_results = self.reranker.rerank_candidates(prompt, candidates, top_k=top_k)
        return reranked_results

    def graph_rag_search(self, cypher_query):
        """Tier 2: Knowledge Graph Traversal via Neo4j Cypher Graph-RAG."""
        try:
            return self.query_neo4j(cypher_query)
        except Exception as e:
            return [{"error": f"Graph Query Exception: {e}"}]

    def semantic_metric_search(self, cube_name, measures, dimensions=None):
        """Tier 3: Cube.js Open-Source Semantic Layer Metric Aggregation."""
        query_body = {
            "measures": [f"{cube_name}.{m}" for m in measures]
        }
        if dimensions:
            query_body["dimensions"] = [f"{cube_name}.{d}" for d in dimensions]

        url_encoded_query = urllib.parse.quote(json.dumps(query_body))
        url = f"{CUBEJS_URL}?query={url_encoded_query}"
        # Was missing this entirely -- cube/cube.js's checkAuth rejects any
        # request with no/invalid Authorization header, so this call failed
        # 100% of the time, and the swallowed exception below returned an
        # error object that flowed into the LLM context as if it were a real
        # metrics result. mcp_server/financial_data_mcp_server.py's
        # query_semantic_metrics always sent this header; this tier had drifted.
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {CUBEJS_API_SECRET}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("data", [])
        except Exception as e:
            return [{"error": str(e)}]

    def relational_sql_search(self, sql_query):
        """Tier 4: Relational SQL Query Execution on PostgreSQL."""
        try:
            return self.query_pg(sql_query)[:10]
        except Exception as e:
            return [{"error": f"SQL Execution Error: {e}"}]

    def hybrid_retrieve(self, prompt, cypher_override=None, sql_override=None):
        """
        Unified Multi-Modal Hybrid RAG Pipeline:
        Combines Vector + Graph-RAG + Semantic Metrics + Relational SQL + AI Guardrails + LLMOps Telemetry.
        """
        pipeline_start = time.time()
        trace = self.telemetry.start_trace(prompt)

        # 0. Check Prompt Injection Defense
        safe, reason = self.guardrails.check_prompt_injection(prompt)
        if not safe:
            logger.warning(reason)
            return {"error": reason, "security_status": "BLOCKED"}

        # Logger, not print(), throughout this method: when the MCP server
        # runs over its default stdio transport, stdout *is* the JSON-RPC
        # channel -- calling hybrid_rag_search (which invokes this method)
        # previously wrote ~15 lines of non-protocol bytes into that framing
        # and broke the session. logging's default handler writes to stderr.
        logger.info(f"Multi-Modal Hybrid RAG Prompt: '{prompt}'")

        # 1. Vector Semantic Search
        t1_start = time.time()
        vector_results = self.vector_semantic_search(prompt, top_k=3)
        self.telemetry.record_tier_latency(trace, "Vector_Search_pgvector", (time.time() - t1_start) * 1000)
        logger.info("Tier 1: 2-Stage Vector & Cross-Encoder Neural Re-Ranking Matches:")
        for v in vector_results:
            logger.info(f"  [{v['entity_type']}] {v['display_name']} — Cross-Encoder Score: {v.get('cross_encoder_score', 'N/A')} (Bi-Encoder Sim: {v.get('similarity')})")

        # 2. Graph-RAG Dynamic Text-to-Cypher Execution
        t2_start = time.time()
        if cypher_override:
            cypher = cypher_override
            intent = "Explicit Cypher Override"
        else:
            cypher, intent = self.cypher_builder.compile_cypher(prompt)

        graph_results = self.graph_rag_search(cypher)
        self.telemetry.record_tier_latency(trace, "Graph_RAG_Neo4j", (time.time() - t2_start) * 1000)
        logger.info(f"Tier 2: Knowledge Graph Traversal (Dynamic Text-to-Cypher: {intent}):")
        for g in graph_results:
            logger.info(f"  {g}")

        # 3. Semantic Metric Layer Calculation
        t3_start = time.time()
        semantic_results = self.semantic_metric_search("deposit_balance", ["total_available_balance"])
        self.telemetry.record_tier_latency(trace, "Semantic_Metrics_Cubejs", (time.time() - t3_start) * 1000)
        logger.info("Tier 3: Semantic Layer Aggregation (Cube.js Metrics):")
        for s in semantic_results:
            logger.info(f"  {s}")

        # 4. Relational SQL Execution
        t4_start = time.time()
        sql = sql_override or "SELECT party_type, count(*) FROM financial.party GROUP BY party_type;"
        sql_results = self.relational_sql_search(sql)
        self.telemetry.record_tier_latency(trace, "Relational_SQL_PostgreSQL", (time.time() - t4_start) * 1000)
        logger.info("Tier 4: Relational Database Execution (PostgreSQL SQL):")
        for s in sql_results:
            logger.info(f"  {s}")

        # Construct Combined RAG Context Payload
        raw_payload = {
            "prompt": prompt,
            "vector_schema_context": vector_results,
            "knowledge_graph_context": graph_results,
            "semantic_metrics_context": semantic_results,
            "relational_sql_context": sql_results
        }

        # 5. Sanitize & Redact PII in Context Payload before returning
        sanitized_payload = self.guardrails.sanitize_context_payload(raw_payload)

        # 6. Finalize LLMOps Telemetry Trace Span
        pipeline_latency_ms = (time.time() - pipeline_start) * 1000
        final_trace = self.telemetry.finalize_trace(trace, json.dumps(sanitized_payload), pipeline_latency_ms)
        sanitized_payload["_telemetry_span"] = {
            "trace_id": final_trace["trace_id"],
            "latency_ms": final_trace["total_latency_ms"],
            "total_tokens": final_trace["total_tokens"],
            "cost_usd": final_trace["cost_usd"]
        }

        # Surfaces whether Tier 1 (vector search) and its re-ranking stage used
        # the real sentence-transformers models or the non-semantic
        # ALLOW_DEGRADED_EMBEDDINGS=1 fallback -- see scripts/_embedding_backend.py.
        # A caller (agent or human) must be able to tell a degraded result from
        # a real one; before this, both looked identical.
        sanitized_payload["_embedding_backend"] = {
            "embedding_mode": EMBEDDING_MODE,
            "reranker_mode": self.reranker.mode,
        }

        return sanitized_payload

def main():
    retriever = HybridRAGRetriever()

    # Test Case 1: Master Party & Account Exposure Inquiry
    prompt1 = "Identify overdrawn deposit account customer risk exposure and master party entities"
    payload1 = retriever.hybrid_retrieve(prompt1)

    # Test Case 2: Credit Agreement & Collateral Analysis
    prompt2 = "Find loan agreements with pledged collateral assets and interest rate terms"
    sql2 = "SELECT agreement_status, COUNT(*), SUM(principal_amount) FROM financial.loan_agreement GROUP BY agreement_status;"
    payload2 = retriever.hybrid_retrieve(prompt2, sql_override=sql2)

    print("\n✅ Multi-Modal Hybrid RAG Retriever Test Successfully Completed!")

if __name__ == "__main__":
    main()
