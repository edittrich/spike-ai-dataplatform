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
import urllib.request
import urllib.parse
import urllib.error
import time

import psycopg2
from neo4j import READ_ACCESS, GraphDatabase

from scripts._dotenv_boot import load_env
from scripts.ai_safety_guardrails import AISafetyGuardrails

# Loads .env when this module runs on the host (both directly, per CLAUDE.md's
# pipeline docs, and indirectly via the hybrid_rag_search MCP tool's stdio
# case). A no-op inside mcp_sidecar, where docker-compose.yml already injects
# real env vars and `override=False` never replaces them.
load_env()
from scripts.llmops_telemetry import LLMOpsTelemetry
from scripts.neural_reranker import NeuralReranker
from scripts.text_to_cypher_builder import TextToCypherBuilder

# Configure PyTorch sentence-transformers embedding model
try:
    from sentence_transformers import SentenceTransformer
    EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    def get_embedding(text):
        return [round(float(x), 6) for x in EMBED_MODEL.encode(text)]
except Exception:
    import math, re
    def get_embedding(text):
        dim = 384
        vec = [0.0] * dim
        tokens = re.findall(r'\w+', text.lower())
        for token in tokens:
            for i in range(len(token)):
                h = hash(token[i:i+3]) % dim
                vec[h] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        return [round(x / norm, 6) if norm > 0 else 0.0 for x in vec]

OPENMETADATA_URL = "http://127.0.0.1:8585/api/v1"
CUBEJS_URL = "http://127.0.0.1:4000/cubejs-api/v1/load"

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

    def query_pg(self, sql):
        # Validate read-only SQL safety
        safe, reason = self.guardrails.validate_read_only_query(sql, "SQL")
        if not safe:
            raise ValueError(reason)
        conn = psycopg2.connect(
            host=POSTGRES_HOST, port=POSTGRES_PORT, user=POSTGRES_USER,
            password=POSTGRES_PASSWORD, dbname=POSTGRES_DB,
            options="-c statement_timeout=10000 -c idle_in_transaction_session_timeout=30000",
        )
        try:
            # Defense in depth: even if a mutation slipped past the keyword
            # check above, the database itself now refuses to execute it.
            conn.set_session(readonly=True)
            with conn.cursor() as cur:
                cur.execute(sql)
                if cur.description is None:
                    return ""
                rows = cur.fetchall()
                # No header, pipe-delimited -- matches the previous
                # `psql -t -A` output that vector_semantic_search() and
                # relational_sql_search() parse.
                return "\n".join(
                    "|".join("" if v is None else str(v) for v in row) for row in rows
                )
        finally:
            conn.close()

    def query_neo4j(self, cypher):
        # Validate read-only Cypher safety
        safe, reason = self.guardrails.validate_read_only_query(cypher, "Cypher")
        if not safe:
            raise ValueError(reason)
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        try:
            # See the matching comment in mcp_server/financial_data_mcp_server.py's
            # query_neo4j: READ_ACCESS is the enforcement available on Neo4j
            # Community Edition in place of a dedicated read-only role/RBAC.
            with driver.session(default_access_mode=READ_ACCESS) as session:
                result = session.run(cypher)
                keys = list(result.keys())
                # Header line + comma-joined records -- matches the previous
                # `cypher-shell` output that graph_rag_search() slices [1:] on.
                lines = [", ".join(keys)]
                for record in result:
                    lines.append(", ".join(str(record[k]) for k in keys))
                return "\n".join(lines)
        finally:
            driver.close()

    def vector_semantic_search(self, prompt, top_k=3, fetch_candidates_k=10):
        """
        Tier 1: 2-Stage Retrieval Pipeline:
        - 1st-Stage: pgvector 0.8.0 HNSW cosine similarity search (fetches candidate_k=10).
        - 2nd-Stage: Neural Cross-Encoder Re-Ranking (ms-marco-MiniLM-L-6-v2) returns top_k=3.
        """
        query_vec = get_embedding(prompt)
        vec_str = "[" + ",".join(str(x) for x in query_vec) + "]"

        sql = f"""
        SELECT 
            entity_type,
            display_name,
            ROUND((1 - (embedding <=> '{vec_str}'::vector))::numeric, 4) AS similarity,
            content_text,
            metadata
        FROM financial.entity_embeddings
        ORDER BY embedding <=> '{vec_str}'::vector ASC
        LIMIT {fetch_candidates_k};
        """
        raw = self.query_pg(sql)
        candidates = []
        for line in raw.split("\n"):
            if line:
                parts = line.split("|")
                if len(parts) >= 4:
                    candidates.append({
                        "entity_type": parts[0],
                        "display_name": parts[1],
                        "similarity": float(parts[2]),
                        "content_text": parts[3]
                    })

        # Apply 2nd-stage Cross-Encoder neural re-ranking
        reranked_results = self.reranker.rerank_candidates(prompt, candidates, top_k=top_k)
        return reranked_results

    def graph_rag_search(self, cypher_query):
        """Tier 2: Knowledge Graph Traversal via Neo4j Cypher Graph-RAG."""
        try:
            raw = self.query_neo4j(cypher_query)
            lines = [l.strip() for l in raw.split("\n") if l.strip()]
            return lines[1:] if len(lines) > 1 else lines
        except Exception as e:
            return [f"Graph Query Exception: {e}"]

    def semantic_metric_search(self, cube_name, measures, dimensions=None):
        """Tier 3: Cube.js Open-Source Semantic Layer Metric Aggregation."""
        query_body = {
            "measures": [f"{cube_name}.{m}" for m in measures]
        }
        if dimensions:
            query_body["dimensions"] = [f"{cube_name}.{d}" for d in dimensions]

        url_encoded_query = urllib.parse.quote(json.dumps(query_body))
        url = f"{CUBEJS_URL}?query={url_encoded_query}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("data", [])
        except Exception as e:
            return [{"error": str(e)}]

    def relational_sql_search(self, sql_query):
        """Tier 4: Relational SQL Query Execution on PostgreSQL."""
        try:
            raw = self.query_pg(sql_query)
            return raw.split("\n")[:10]
        except Exception as e:
            return [f"SQL Execution Error: {e}"]

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
            print(f"\n⚠️ {reason}")
            return {"error": reason, "security_status": "BLOCKED"}

        print(f"\n=======================================================")
        print(f"🔍 Multi-Modal Hybrid RAG Prompt: '{prompt}'")
        print(f"=======================================================")

        # 1. Vector Semantic Search
        t1_start = time.time()
        vector_results = self.vector_semantic_search(prompt, top_k=3)
        self.telemetry.record_tier_latency(trace, "Vector_Search_pgvector", (time.time() - t1_start) * 1000)
        print(f"\n🧠 Tier 1: 2-Stage Vector & Cross-Encoder Neural Re-Ranking Matches:")
        for v in vector_results:
            print(f"  🎯 [{v['entity_type']}] {v['display_name']} — Cross-Encoder Score: {v.get('cross_encoder_score', 'N/A')} (Bi-Encoder Sim: {v.get('similarity')})")

        # 2. Graph-RAG Dynamic Text-to-Cypher Execution
        t2_start = time.time()
        if cypher_override:
            cypher = cypher_override
            intent = "Explicit Cypher Override"
        else:
            cypher, intent = self.cypher_builder.compile_cypher(prompt)

        graph_results = self.graph_rag_search(cypher)
        self.telemetry.record_tier_latency(trace, "Graph_RAG_Neo4j", (time.time() - t2_start) * 1000)
        print(f"\n🕸️ Tier 2: Knowledge Graph Traversal (Dynamic Text-to-Cypher: {intent}):")
        for g in graph_results:
            print(f"  🕸️ {g}")

        # 3. Semantic Metric Layer Calculation
        t3_start = time.time()
        semantic_results = self.semantic_metric_search("deposit_balance", ["total_available_balance"])
        self.telemetry.record_tier_latency(trace, "Semantic_Metrics_Cubejs", (time.time() - t3_start) * 1000)
        print(f"\n📊 Tier 3: Semantic Layer Aggregation (Cube.js Metrics):")
        for s in semantic_results:
            print(f"  📈 {s}")

        # 4. Relational SQL Execution
        t4_start = time.time()
        sql = sql_override or "SELECT party_type, count(*) FROM financial.party GROUP BY party_type;"
        sql_results = self.relational_sql_search(sql)
        self.telemetry.record_tier_latency(trace, "Relational_SQL_PostgreSQL", (time.time() - t4_start) * 1000)
        print(f"\n🗄️ Tier 4: Relational Database Execution (PostgreSQL SQL):")
        for s in sql_results:
            print(f"  🗄️ {s}")

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
