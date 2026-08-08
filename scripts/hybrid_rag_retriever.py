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
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from neo4j import READ_ACCESS, Driver, GraphDatabase

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
from scripts.text_to_cypher_builder import (
    INTENT_AML_RISK,
    INTENT_COLLATERAL,
    INTENT_DEFAULT,
    INTENT_DEPOSIT,
    TextToCypherBuilder,
)

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

# Q3 (hardening plan): "the 4-tier hybrid RAG is two dynamic tiers plus two
# constants" -- Tier 3 always requested deposit_balance.total_available_balance
# and Tier 4 always ran a fixed party_type count query, regardless of the
# prompt. Both now route on the SAME shared intent classification Tier 2
# already used (scripts.text_to_cypher_builder.classify_intent), so all three
# dynamic tiers agree on what the user asked about instead of each guessing
# independently (or, for Tiers 3/4 previously, not guessing at all).
#
# (cube_name, measures, dimensions) per intent for Tier 3. Every measure
# combination below was verified live against the running Cube.js container
# -- in particular, deposit_account.total_available_balance cannot be
# combined with any other deposit_account measure in one query (a real
# Cube.js v0.35 bug hit during Phase 4's pre_aggregations work: it references
# a joined cube's column and the combined query fails with a "row
# multiplication" FROM-clause error), so the deposit intent uses two
# same-cube, own-column count measures instead, which combine safely.
TIER3_INTENT_QUERY_MAP = {
    INTENT_COLLATERAL: ("loan_collateral", ["total_collateral_assets", "total_appraised_value"], None),
    INTENT_DEPOSIT: ("deposit_account", ["total_deposit_accounts", "overdrawn_account_count"], None),
    INTENT_AML_RISK: ("party_role_customer", ["high_aml_risk_count", "active_customers_count"], None),
    INTENT_DEFAULT: ("party", ["total_party_masters"], None),
}

# Read-only SQL per intent for Tier 4. Every query verified live against the
# real database and returns real, non-empty results.
TIER4_INTENT_QUERY_MAP = {
    INTENT_COLLATERAL: (
        "SELECT collateral_type, COUNT(*) AS asset_count, SUM(estimated_value) AS total_value "
        "FROM financial.loan_collateral WHERE md_is_active = TRUE "
        "GROUP BY collateral_type ORDER BY total_value DESC LIMIT 10;"
    ),
    INTENT_DEPOSIT: (
        "SELECT da.account_type, COUNT(*) AS account_count, SUM(db.available_balance) AS total_available_balance "
        "FROM financial.deposit_account da JOIN financial.deposit_balance db "
        "ON da.deposit_account_id = db.deposit_account_id "
        "WHERE da.md_is_active = TRUE AND db.md_is_active = TRUE "
        "GROUP BY da.account_type ORDER BY total_available_balance DESC LIMIT 10;"
    ),
    INTENT_AML_RISK: (
        "SELECT aml_risk_rating, kyc_status, COUNT(*) AS customer_count "
        "FROM financial.party_role_customer WHERE md_is_active = TRUE "
        "GROUP BY aml_risk_rating, kyc_status ORDER BY customer_count DESC LIMIT 10;"
    ),
    # Unchanged from the previous hardcoded default -- still the right
    # "no specific intent, give a basic overview" query, now reached via
    # classification instead of being the only option.
    INTENT_DEFAULT: "SELECT party_type, count(*) FROM financial.party GROUP BY party_type;",
}


class HybridRAGRetriever:
    def __init__(self) -> None:
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

    def _get_pg_conn(self) -> "psycopg2.extensions.connection":
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

    def _get_neo4j_driver(self) -> Driver:
        if self._neo4j_driver is None:
            self._neo4j_driver = GraphDatabase.driver(
                NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD), connection_timeout=10
            )
        return self._neo4j_driver

    def close(self) -> None:
        """Releases this instance's pooled connections. Optional to call --
        the OS reclaims the sockets at process exit regardless -- but worth
        calling explicitly if constructing many short-lived retriever
        instances in a loop rather than one long-lived instance."""
        if self._pg_conn is not None and not self._pg_conn.closed:
            self._pg_conn.close()
        if self._neo4j_driver is not None:
            self._neo4j_driver.close()
            self._neo4j_driver = None

    def query_pg(self, sql: str, params: Optional[Tuple[Any, ...]] = None) -> List[Dict[str, Any]]:
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

    def query_neo4j(self, cypher: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
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

    def vector_semantic_search(
        self, prompt: str, top_k: int = 3, fetch_candidates_k: int = 10
    ) -> List[Dict[str, Any]]:
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

    def graph_rag_search(self, cypher_query: str) -> List[Dict[str, Any]]:
        """Tier 2: Knowledge Graph Traversal via Neo4j Cypher Graph-RAG.

        Q4 (hardening plan): this used to catch every exception and return
        `[{"error": "..."}]` -- a list of dicts, exactly the shape a real
        result takes, so the caller (and the LLM the payload is ultimately
        built for) had no way to tell a failed tier from one that genuinely
        found a single record containing the word "error". Now lets the
        exception propagate; hybrid_retrieve's per-tier try/except is the
        single place that decides what a failure looks like in the final
        payload (an empty list plus a real, separate entry in
        `_tier_errors` -- never a fake data row)."""
        return self.query_neo4j(cypher_query)

    def semantic_metric_search(
        self, cube_name: str, measures: List[str], dimensions: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Tier 3: Cube.js Open-Source Semantic Layer Metric Aggregation.
        See graph_rag_search's docstring -- same Q4 fix, same reasoning."""
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
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", [])

    def relational_sql_search(self, sql_query: str) -> List[Dict[str, Any]]:
        """Tier 4: Relational SQL Query Execution on PostgreSQL.
        See graph_rag_search's docstring -- same Q4 fix, same reasoning."""
        return self.query_pg(sql_query)[:10]

    def hybrid_retrieve(
        self,
        prompt: str,
        cypher_override: Optional[str] = None,
        sql_override: Optional[str] = None,
    ) -> Dict[str, Any]:
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

        # Q4 (hardening plan): "21 broad except Exception clauses, most
        # converting failures into values that look like results... put
        # exception text directly into knowledge_graph_context, so the LLM
        # sees stack messages as retrieved evidence." tier_errors is the
        # out-of-band home for a tier's failure instead -- populated only on
        # a real exception, attached to the final payload separately from
        # the *_context fields (which stay a genuinely empty list on
        # failure, never a fake error-shaped row).
        tier_errors = {}

        # 1. Vector Semantic Search
        t1_start = time.time()
        vector_results = self.vector_semantic_search(prompt, top_k=3)
        self.telemetry.record_tier_latency(trace, "Vector_Search_pgvector", (time.time() - t1_start) * 1000)
        logger.info("Tier 1: 2-Stage Vector & Cross-Encoder Neural Re-Ranking Matches:")
        for v in vector_results:
            logger.info(f"  [{v['entity_type']}] {v['display_name']} — Cross-Encoder Score: {v.get('cross_encoder_score', 'N/A')} (Bi-Encoder Sim: {v.get('similarity')})")

        # Q3 (hardening plan): classified once, shared by Tiers 2, 3, and 4
        # below, so all three dynamic tiers agree on what the prompt is
        # asking about -- see TIER3_INTENT_QUERY_MAP/TIER4_INTENT_QUERY_MAP's
        # module-level comment.
        shared_intent = self.cypher_builder.classify_intent(prompt)

        # 2. Graph-RAG Dynamic Text-to-Cypher Execution
        t2_start = time.time()
        if cypher_override:
            cypher = cypher_override
            intent = "Explicit Cypher Override"
        else:
            cypher, intent = self.cypher_builder.compile_cypher(prompt)

        try:
            graph_results = self.graph_rag_search(cypher)
        except Exception as e:
            logger.error(f"Tier 2 (Graph_RAG_Neo4j) failed: {e}")
            tier_errors["Graph_RAG_Neo4j"] = str(e)
            graph_results = []
        self.telemetry.record_tier_latency(trace, "Graph_RAG_Neo4j", (time.time() - t2_start) * 1000)
        logger.info(f"Tier 2: Knowledge Graph Traversal (Dynamic Text-to-Cypher: {intent}):")
        for g in graph_results:
            logger.info(f"  {g}")

        # 3. Semantic Metric Layer Calculation
        # Q3: previously always requested deposit_balance.total_available_balance
        # regardless of the prompt -- now routes on shared_intent, the same
        # classification driving Tier 2 above.
        t3_start = time.time()
        tier3_cube, tier3_measures, tier3_dimensions = TIER3_INTENT_QUERY_MAP[shared_intent]
        try:
            semantic_results = self.semantic_metric_search(tier3_cube, tier3_measures, tier3_dimensions)
        except Exception as e:
            logger.error(f"Tier 3 (Semantic_Metrics_Cubejs) failed: {e}")
            tier_errors["Semantic_Metrics_Cubejs"] = str(e)
            semantic_results = []
        self.telemetry.record_tier_latency(trace, "Semantic_Metrics_Cubejs", (time.time() - t3_start) * 1000)
        logger.info(f"Tier 3: Semantic Layer Aggregation (Cube.js Metrics, intent={shared_intent}):")
        for s in semantic_results:
            logger.info(f"  {s}")

        # 4. Relational SQL Execution
        # Q3: previously always ran the same fixed party_type count query
        # regardless of the prompt -- now routes on shared_intent too.
        t4_start = time.time()
        sql = sql_override or TIER4_INTENT_QUERY_MAP[shared_intent]
        try:
            sql_results = self.relational_sql_search(sql)
        except Exception as e:
            logger.error(f"Tier 4 (Relational_SQL_PostgreSQL) failed: {e}")
            tier_errors["Relational_SQL_PostgreSQL"] = str(e)
            sql_results = []
        self.telemetry.record_tier_latency(trace, "Relational_SQL_PostgreSQL", (time.time() - t4_start) * 1000)
        logger.info(f"Tier 4: Relational Database Execution (PostgreSQL SQL, intent={shared_intent}):")
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

        # Q4: attached out-of-band, alongside (not inside) the *_context
        # fields -- empty dict when every tier succeeded, so a caller can
        # check `bool(_tier_errors)` rather than having to inspect each
        # context list for a suspicious-looking single "error" record.
        sanitized_payload["_tier_errors"] = tier_errors

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

def main() -> None:
    retriever = HybridRAGRetriever()

    # Test Case 1: Master Party & Account Exposure Inquiry
    prompt1 = "Identify overdrawn deposit account customer risk exposure and master party entities"
    payload1 = retriever.hybrid_retrieve(prompt1)
    assert "_tier_errors" in payload1, "Q4 regression: payload missing _tier_errors"
    print(f"  Test Case 1 tier_errors: {payload1['_tier_errors']}")

    # Test Case 2: Credit Agreement & Collateral Analysis
    prompt2 = "Find loan agreements with pledged collateral assets and interest rate terms"
    sql2 = "SELECT agreement_status, COUNT(*), SUM(principal_amount) FROM financial.loan_agreement GROUP BY agreement_status;"
    payload2 = retriever.hybrid_retrieve(prompt2, sql_override=sql2)
    assert "_tier_errors" in payload2, "Q4 regression: payload missing _tier_errors"
    print(f"  Test Case 2 tier_errors: {payload2['_tier_errors']}")

    print("\n✅ Multi-Modal Hybrid RAG Retriever Test Successfully Completed!")

if __name__ == "__main__":
    main()
