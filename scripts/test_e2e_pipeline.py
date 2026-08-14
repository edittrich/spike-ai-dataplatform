#!/usr/bin/env python3
"""
===============================================================================
End-to-End (E2E) Application Test Suite against the configured LLM provider
===============================================================================
Executes a complete 360° E2E workflow:
1. Prompt Guardrails Security Audit (PII Masking & Injection Check)
2. Multi-Modal 4-Tier Hybrid RAG Context Retrieval:
   - Tier 1: pgvector 0.8.0 Dense Vector Similarity Search
   - Tier 2: Neo4j Cypher Multi-Hop Knowledge Graph Traversal
   - Tier 3: Cube.js Semantic Metric Layer Aggregation
   - Tier 4: Supabase PostgreSQL Read-Only SQL Execution
3. FastMCP Server Tool Dispatch & Context Payload Formatting
4. LLM Inference via the configured provider (LLM_PROVIDER: ollama | moonshot)
5. LLMOps Telemetry, Cost Accounting ($0.00) & OpenTelemetry Span Export
===============================================================================
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import asyncio

from scripts._dotenv_boot import load_env

# Loaded before _llm_backend is used so the provider credentials in .env are
# visible when this script is run directly (its documented usage). Idempotent.
load_env()

from scripts._llm_backend import LLMBackendError, get_llm_backend  # noqa: E402
from scripts.ai_safety_guardrails import AISafetyGuardrails
from scripts.hybrid_rag_retriever import HybridRAGRetriever
from scripts.llmops_telemetry import LLMOpsTelemetry
from mcp_server.financial_data_mcp_server import mcp


def call_llm(prompt_text: str, context_payload: dict) -> dict:
    """Invokes the configured LLM backend (Ollama or Moonshot) with RAG context."""
    system_prompt = (
        "You are an expert Financial Risk & Enterprise Data Platform AI Assistant. "
        "Analyze the provided multi-modal RAG context and answer the user question."
    )
    full_prompt = (
        f"{system_prompt}\n\n"
        f"--- GROUNDED RAG CONTEXT ---\n{json.dumps(context_payload, indent=2)}\n\n"
        f"--- USER QUESTION ---\n{prompt_text}\n\n"
        f"--- RESPONSE ---"
    )
    try:
        backend = get_llm_backend()
        result = backend.chat([{"role": "user", "content": full_prompt}], temperature=0.2)
        return {
            "response": result.content,
            "prompt_eval_count": result.prompt_tokens,
            "eval_count": result.completion_tokens,
            "llm_latency_ms": result.latency_ms,
            "model_label": result.model_label,
        }
    except LLMBackendError as e:
        return {"error": f"LLM Call Error: {e}", "llm_latency_ms": 0}


async def run_e2e_pipeline():
    print("🚀 Starting End-to-End (E2E) Application Test against the configured LLM...")
    print("==================================================================================")

    # Test Inquiry
    user_prompt = "Identify overdrawn deposit account customer risk exposure, collateral values, and total available balance"
    
    # -------------------------------------------------------------------------
    # STEP 1: AI Safety Guardrails
    # -------------------------------------------------------------------------
    print("\n🛡️ Step 1: AI Safety & Real-Time Prompt Guardrails Audit...")
    guardrails = AISafetyGuardrails()
    is_safe, msg = guardrails.check_prompt_injection(user_prompt)
    if not is_safe:
        print(f"❌ Security Block: {msg}")
        return
    print("  ✅ Prompt Guardrail Validation: PASSED (Clean of injections & threats)")

    # -------------------------------------------------------------------------
    # STEP 2: Multi-Modal 4-Tier Hybrid RAG Context Retrieval
    # -------------------------------------------------------------------------
    print("\n🔍 Step 2: Multi-Modal Hybrid RAG Context Retrieval...")
    retriever = HybridRAGRetriever()
    rag_payload = retriever.hybrid_retrieve(user_prompt)

    # Each tier's status line reflects what actually came back, rather than
    # printing "✅ ... " unconditionally regardless of the payload's content
    # (which previously included a hardcoded "$63.5M" for Tier 3 -- whatever
    # the real value was).
    #
    # Q4 (hardening plan): this used to detect a failed tier by sniffing its
    # context list for the word "Error"/"Exception" or an `"error"` dict key
    # -- a heuristic that only existed because failed tiers used to return
    # `[{"error": "..."}]`, a fake row shaped like real data. Now that
    # hybrid_retrieve() reports failures out-of-band in `_tier_errors`
    # instead (a genuinely empty list on failure, never a fake row), this
    # checks that directly -- more accurate (no risk of a false positive on
    # real data that happens to contain the word "Error", e.g. an account
    # status of "ERROR_PENDING_REVIEW") and no longer checking for a shape
    # that can't occur anymore.
    step_failures = []
    tier_errors = rag_payload.get("_tier_errors", {})

    vector_ctx = rag_payload.get("vector_schema_context", [])
    if vector_ctx:
        embed_mode = rag_payload.get("_embedding_backend", {}).get("embedding_mode", "unknown")
        print(f"  {'✅' if embed_mode == 'real' else '⚠️'} Tier 1 (pgvector HNSW): {len(vector_ctx)} entity match(es), embedding_mode={embed_mode}")
    else:
        step_failures.append("Tier 1 (pgvector)")
        print("  ❌ Tier 1 (pgvector HNSW): no matches returned")

    graph_ctx = rag_payload.get("knowledge_graph_context", [])
    if graph_ctx and "Graph_RAG_Neo4j" not in tier_errors:
        print(f"  ✅ Tier 2 (Neo4j Graph-RAG): {len(graph_ctx)} row(s) returned")
    else:
        step_failures.append("Tier 2 (Neo4j)")
        print(f"  ❌ Tier 2 (Neo4j Graph-RAG): {tier_errors.get('Graph_RAG_Neo4j', 'no rows returned')[:120]}")

    semantic_ctx = rag_payload.get("semantic_metrics_context", [])
    if semantic_ctx and "Semantic_Metrics_Cubejs" not in tier_errors:
        print(f"  ✅ Tier 3 (Cube.js Metrics): {semantic_ctx}")
    else:
        step_failures.append("Tier 3 (Cube.js)")
        print(f"  ❌ Tier 3 (Cube.js Metrics): {tier_errors.get('Semantic_Metrics_Cubejs', 'no data returned')}")

    sql_ctx = rag_payload.get("relational_sql_context", [])
    if sql_ctx and "Relational_SQL_PostgreSQL" not in tier_errors:
        print(f"  ✅ Tier 4 (Supabase SQL): {len(sql_ctx)} row(s) fetched")
    else:
        step_failures.append("Tier 4 (Supabase SQL)")
        print(f"  ❌ Tier 4 (Supabase SQL): {tier_errors.get('Relational_SQL_PostgreSQL', 'no rows returned')[:120]}")

    # -------------------------------------------------------------------------
    # STEP 3: FastMCP Tool Verification
    # -------------------------------------------------------------------------
    print("\n🔌 Step 3: FastMCP Tool Dispatch & Context Formatting...")
    mcp_catalog_res = await mcp.call_tool("search_data_catalog", {"query": "deposit_account"})
    catalog_str = str(mcp_catalog_res)
    if "Error" in catalog_str:
        step_failures.append("FastMCP search_data_catalog")
        print(f"  ❌ FastMCP `search_data_catalog` tool returned an error: {catalog_str[:150]}")
    else:
        print("  ✅ FastMCP `search_data_catalog` tool invoked successfully")

    # -------------------------------------------------------------------------
    # STEP 4: LLM Inference via the configured provider
    # -------------------------------------------------------------------------
    print("\n🤖 Step 4: Invoking the configured LLM inference engine...")
    llm_res = call_llm(user_prompt, rag_payload)

    if "error" in llm_res:
        print(f"❌ LLM Error: {llm_res['error']}")
        return

    print("\n" + "="*80)
    print("💬 GENERATED RESPONSE:")
    print("="*80)
    print(llm_res["response"])
    print("="*80)

    # -------------------------------------------------------------------------
    # STEP 5: LLMOps Telemetry & Observability Audit
    # -------------------------------------------------------------------------
    print("\n📊 Step 5: LLMOps Telemetry & OpenTelemetry Span Export...")
    telemetry = LLMOpsTelemetry()
    trace = telemetry.start_trace(user_prompt, model=llm_res.get("model_label", "unknown"))
    
    # Record LLM inference metrics
    total_tokens = llm_res["prompt_eval_count"] + llm_res["eval_count"]
    final_span = telemetry.finalize_trace(
        trace, 
        llm_res["response"], 
        total_latency_ms=rag_payload.get("_telemetry_span", {}).get("latency_ms", 0) + llm_res["llm_latency_ms"]
    )

    print(f"  🎯 Model:            {llm_res.get('model_label', 'unknown')}")
    print(f"  🎯 Prompt Tokens:    {llm_res['prompt_eval_count']}")
    print(f"  🎯 Output Tokens:    {llm_res['eval_count']}")
    print(f"  🎯 Total Tokens:     {total_tokens}")
    print(f"  🎯 LLM Latency:      {llm_res['llm_latency_ms']}ms")
    print(f"  🎯 Cumulative Cost:  ${final_span['cost_usd']:.6f} USD")
    print(f"  🎯 OpenTelemetry ID: {final_span['trace_id']}")

    if step_failures:
        print(f"\n⚠️  E2E test completed with {len(step_failures)} tier(s)/tool(s) reporting errors: {', '.join(step_failures)}")
        sys.exit(1)
    print("\n✨ E2E application test completed -- all tiers and tools returned data.")

if __name__ == "__main__":
    asyncio.run(run_e2e_pipeline())
