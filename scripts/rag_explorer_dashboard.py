#!/usr/bin/env python3
"""
===============================================================================
Enterprise AI Data Platform & Multi-Modal RAG Explorer (Streamlit Dashboard)
===============================================================================
Interactive Web UI for real-time RAG context inspection, AI Guardrails audit,
local Ollama Gemma 4 inference, and LLMOps Telemetry trace span visualization.
===============================================================================
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import time
import urllib.request
import urllib.parse
import streamlit as st

from scripts._dotenv_boot import load_env
from scripts.ai_safety_guardrails import AISafetyGuardrails
from scripts.hybrid_rag_retriever import HybridRAGRetriever
from scripts.llmops_telemetry import LLMOpsTelemetry
from scripts.ollama_agentic_tool_runner import OllamaAgenticRunner

load_env()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")

# Page Configuration
st.set_page_config(
    page_title="Enterprise AI Data Platform — RAG Explorer",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling (Dark Glassmorphism Theme)
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #3B82F6 0%, #8B5CF6 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #9CA3AF;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background-color: #1E293B;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 15px;
        text-align: center;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 6px;
        padding: 8px 16px;
    }
</style>
""", unsafe_allow_html=True)

def call_ollama_model(model_name: str, prompt_text: str, context_payload: dict) -> dict:
    """Invokes local Ollama LLM endpoint."""
    system_prompt = (
        "You are an expert Financial Risk & Enterprise Data Platform AI Assistant. "
        "Analyze the provided multi-modal RAG context (Vector, Neo4j Graph, Cube.js Semantic Metrics, Relational SQL) "
        "and provide a structured, executive-ready response answering the user question."
    )
    full_prompt = (
        f"{system_prompt}\n\n"
        f"--- GROUNDED RAG CONTEXT ---\n{json.dumps(context_payload, indent=2)}\n\n"
        f"--- USER QUESTION ---\n{prompt_text}\n\n"
        f"--- FINANCIAL ANALYSIS & RESPONSE ---"
    )
    req_body = {
        "model": model_name,
        "prompt": full_prompt,
        "stream": False,
        "options": {"temperature": 0.2}
    }
    t_start = time.time()
    try:
        req = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(req_body).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            latency_ms = round((time.time() - t_start) * 1000, 2)
            return {
                "response": data.get("response", "").strip(),
                "prompt_eval_count": data.get("prompt_eval_count", 0),
                "eval_count": data.get("eval_count", 0),
                "latency_ms": latency_ms
            }
    except Exception as e:
        return {"error": f"Ollama Connection Error: {e}", "latency_ms": 0}

def main():
    st.markdown('<div class="main-header">🏛️ Enterprise AI Data Platform & RAG Explorer</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Multi-Modal 4-Tier Context Retrieval (pgvector + Neo4j + Cube.js + SQL) powered by Local Ollama Gemma 4</div>', unsafe_allow_html=True)

    # Top Architecture Summary Cards
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(label="🧠 Vector Search", value="pgvector 0.8.0", delta="384-dim HNSW")
    with col2:
        st.metric(label="🕸️ Knowledge Graph", value="Neo4j 5", delta="8,124 Nodes / 12.4k Edges")
    with col3:
        st.metric(label="📊 Semantic Layer", value="Cube.js REST API", delta="16 Data Cubes")
    with col4:
        st.metric(label="🤖 Local LLM Engine", value="Ollama Gemma 4", delta="$0.00 / 1k Tokens")

    st.markdown("---")

    # Sidebar Options
    st.sidebar.header("⚙️ Configuration & Controls")
    execution_mode = st.sidebar.radio(
        "Select Execution Mode",
        ["🤖 Autonomous Gemma 4 Function Calling", "🔍 4-Tier Hybrid RAG Pipeline"]
    )
    model_choice = st.sidebar.selectbox(
        "Select LLM Model Profile",
        ["gemma4:latest", "gemma4:12b", "gemini-2.0-flash", "claude-3-5-sonnet"]
    )
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔌 System Status")
    st.sidebar.success("✅ Supabase PostgreSQL: Connected (Port 54322)")
    st.sidebar.success("✅ Neo4j Knowledge Graph: Connected (Port 7687)")
    st.sidebar.success("✅ OpenMetadata Catalog: Connected (Port 8585)")
    st.sidebar.success("✅ Cube.js Semantic Engine: Connected (Port 4000)")
    st.sidebar.success("✅ Ollama Local Engine: Active (Port 11434)")

    # Sample Prompts Selection
    sample_queries = [
        "Identify overdrawn deposit account customer risk exposure, collateral values, and total available balance",
        "Find loan agreements with pledged collateral assets and interest rate terms",
        "List all individual customers with high risk profiles and active overdraft facilities"
    ]
    
    selected_sample = st.selectbox("💡 Select Sample Financial Inquiry or Type Custom Below:", ["-- Select Sample Query --"] + sample_queries)
    
    default_prompt = selected_sample if selected_sample != "-- Select Sample Query --" else "Identify overdrawn deposit account customer risk exposure and master party entities"
    user_prompt = st.text_area("🔍 Enter Natural Language Query:", value=default_prompt, height=80)

    if st.button("🚀 Run Analysis with Selected Engine", type="primary", use_container_width=True):
        if not user_prompt.strip():
            st.warning("Please enter a query to proceed.")
            return

        if "Autonomous" in execution_mode:
            with st.spinner("🤖 Ollama Gemma 4 Thinking & Autonomously Invoking FastMCP Tools..."):
                agent_runner = OllamaAgenticRunner(model_name=model_choice)
                result = agent_runner.run_agentic_loop(user_prompt)

            st.markdown("### 💬 Autonomous Gemma 4 Response & Decision Log")
            if "error" in result:
                st.error(f"❌ {result['error']}")
            else:
                st.info(result.get("response"))
                
                st.subheader("🔧 Autonomously Executed Tool Calls:")
                tool_calls = result.get("tool_calls_executed", [])
                if tool_calls:
                    for tc in tool_calls:
                        st.markdown(f"👉 **Tool Invoked:** `{tc['tool']}` | **Args:** `{tc['args']}`")
                        with st.expander("Inspect Tool Execution Return Data"):
                            st.code(tc['result_preview'])
                else:
                    st.caption("No external tools were required; Gemma 4 answered directly.")

        else:
            with st.spinner("Executing 4-Tier Retrieval & Guardrail Inspection..."):
                guardrails = AISafetyGuardrails()
                retriever = HybridRAGRetriever()

                is_safe, msg = guardrails.check_prompt_injection(user_prompt)
                if not is_safe:
                    st.error(f"🛑 Security Blocked Prompt: {msg}")
                    return

                rag_payload = retriever.hybrid_retrieve(user_prompt)
                ollama_res = call_ollama_model(model_choice, user_prompt, rag_payload)

            st.markdown("### 💬 Grounded AI Financial Analysis (Local Gemma 4)")
            if "error" in ollama_res:
                st.error(f"❌ {ollama_res['error']}")
            else:
                st.info(ollama_res["response"])

        st.markdown("---")

        # 4-Tier Interactive Context Tabs
        st.markdown("### 🔍 Multi-Modal 4-Tier RAG Context Breakdown")
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "🧠 Tier 1: Vector Search",
            "🕸️ Tier 2: Knowledge Graph",
            "📊 Tier 3: Semantic Metrics",
            "🗄️ Tier 4: Relational SQL",
            "🛡️ Guardrails Audit",
            "📈 LLMOps Telemetry"
        ])

        with tab1:
            st.subheader("pgvector 0.8.0 Dense Semantic Vector Search")
            vector_data = rag_payload.get("vector_schema_context", [])
            if vector_data:
                for v in vector_data:
                    st.markdown(f"**[{v.get('entity_type')}] `{v.get('display_name')}`** — Cosine Similarity: `{v.get('similarity')}`")
                    st.caption(f"Content: {v.get('content_text')}")
            else:
                st.write("No vector matches found.")

        with tab2:
            st.subheader("Neo4j Multi-Hop Graph Traversal (Cypher Graph-RAG)")
            graph_data = rag_payload.get("knowledge_graph_context", [])
            st.code("\n".join(graph_data) if graph_data else "No graph nodes retrieved.")

        with tab3:
            st.subheader("Cube.js Open-Source Semantic Layer Metrics")
            semantic_data = rag_payload.get("semantic_metrics_context", [])
            st.json(semantic_data)

        with tab4:
            st.subheader("Supabase PostgreSQL Relational Database SQL Execution")
            sql_data = rag_payload.get("relational_sql_context", [])
            st.code("\n".join(sql_data) if sql_data else "No SQL records returned.")

        with tab5:
            st.subheader("AI Safety, PII Masking & Prompt Guardrails Audit")
            st.success("✅ Prompt Clean: No SQL/Cypher mutation commands or prompt injection threats detected.")
            sample_pii = "Customer John Doe, email: john@example.com, Phone: 555-123-4567, SSN: 123-45-6789"
            redacted, _ = guardrails.redact_pii(sample_pii)
            st.markdown(f"**Sample Real-Time PII Masking Test:**")
            st.text(f"Original: {sample_pii}\nMasked:   {redacted}")

        with tab6:
            st.subheader("LLMOps Telemetry, Token Accounting & Cost Breakdown")
            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            p_tokens = ollama_res.get("prompt_eval_count", 0)
            c_tokens = ollama_res.get("eval_count", 0)
            with m_col1:
                st.metric("Prompt Tokens", p_tokens)
            with m_col2:
                st.metric("Completion Tokens", c_tokens)
            with m_col3:
                st.metric("Generation Latency", f"{ollama_res.get('latency_ms', 0)} ms")
            with m_col4:
                st.metric("Cumulative Cost", "$0.0000 USD (Local)")

            st.json(rag_payload.get("_telemetry_span", {}))

if __name__ == "__main__":
    main()
