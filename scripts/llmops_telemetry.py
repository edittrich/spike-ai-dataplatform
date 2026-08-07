#!/usr/bin/env python3
"""
===============================================================================
LLMOps Telemetry & Observability Engine
===============================================================================
Tracks, audits, and exports real-time performance telemetry for AI workflows:
1. Token Accounting & LLM Cost Estimation ($ USD)
2. Sub-Millisecond Multi-Tier Latency Breakdown (Vector, Graph, Semantic, SQL)
3. OpenTelemetry-Compatible JSON Trace Spans & Audit Logs
4. Aggregate Telemetry Dashboard & Performance Metrics
===============================================================================
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import time
import json
import uuid
import logging
import collections
from typing import Dict, List, Any, Optional

from prometheus_client import Counter, Histogram

from scripts.ai_safety_guardrails import AISafetyGuardrails

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("LLMOpsTelemetry")

# Process-global Prometheus metrics (module-level, per prometheus_client's own
# convention -- Counter/Histogram accumulate across every LLMOpsTelemetry
# instance in this process, unlike the per-instance `trace_history` below).
# This is what makes real metrics possible at all: the previous design served
# `/metrics` from a *separate* container process
# (scripts/telemetry_metrics_exporter_server.py, now removed) that could never
# see traces recorded by a different process no matter what fed it -- which is
# exactly why it was seeded with `random.uniform()` fake data instead. These
# are now read directly by the process doing the actual work
# (mcp_server/financial_data_mcp_server.py, which calls
# `prometheus_client.start_http_server()` to expose them) rather than shipped
# to a simulator.
TRACES_TOTAL = Counter(
    "llmops_traces_total", "Total number of LLMOps traces completed.", ["model"]
)
TOKENS_TOTAL = Counter(
    "llmops_tokens_total", "Total tokens processed (prompt + completion, estimated).", ["model"]
)
COST_USD_TOTAL = Counter(
    "llmops_cost_usd_total", "Cumulative estimated LLM inference cost in USD.", ["model"]
)
TOTAL_LATENCY_MS = Histogram(
    "llmops_total_latency_ms",
    "End-to-end pipeline latency per trace, in milliseconds.",
    buckets=(10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)
TIER_LATENCY_MS = Histogram(
    "llmops_tier_latency_ms",
    "Per-tier retrieval latency, in milliseconds.",
    ["tier"],
    buckets=(5, 10, 25, 50, 100, 250, 500, 1000, 2500),
)

# Standard Model Pricing per 1,000 Tokens (USD)
MODEL_PRICING = {
    "ollama/gemma4": {"input": 0.00000, "output": 0.00000},
    "ollama/gemma2": {"input": 0.00000, "output": 0.00000},
    "sentence-transformers/all-MiniLM-L6-v2": {"input": 0.00000, "output": 0.00000},
    "gemini-2.0-flash": {"input": 0.00010, "output": 0.00040},
    "claude-3-5-sonnet": {"input": 0.00300, "output": 0.01500},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.00060}
}

# Cap on the in-process trace_history used by export_telemetry_dashboard()'s
# per-instance JSON view -- previously an unbounded list, which in a
# `restart: always` container is a slow memory leak over the container's
# lifetime. The real, unbounded-in-effect metrics now live in the
# process-global Prometheus objects above, which store fixed-size bucket
# counts rather than one entry per trace.
MAX_TRACE_HISTORY = 500

class LLMOpsTelemetry:
    def __init__(self):
        self.trace_history = collections.deque(maxlen=MAX_TRACE_HISTORY)
        self.guardrails = AISafetyGuardrails()

    def estimate_tokens(self, text: str) -> int:
        """Approximates token count based on standard ~4 characters per token heuristic."""
        if not text:
            return 0
        return max(1, len(text) // 4)

    def calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculates estimated cost ($ USD) based on model token rates."""
        pricing = MODEL_PRICING.get(model, {"input": 0.00000, "output": 0.00000})
        cost_in = (prompt_tokens / 1000.0) * pricing["input"]
        cost_out = (completion_tokens / 1000.0) * pricing["output"]
        return round(cost_in + cost_out, 6)

    def start_trace(self, prompt: str, model: str = "ollama/gemma4") -> Dict[str, Any]:
        """Starts a new OpenTelemetry-compatible trace span."""
        trace_id = f"trace-{uuid.uuid4().hex[:12]}"
        span_id = f"span-{uuid.uuid4().hex[:8]}"
        # Token/cost accounting uses the real prompt length; only the text
        # persisted into trace_history (and any future export) is redacted --
        # this trace previously stored the raw, unredacted prompt, unlike the
        # RAG context payload which already goes through sanitize_context_payload.
        prompt_tokens = self.estimate_tokens(prompt)
        redacted_prompt, _ = self.guardrails.redact_pii(prompt)

        return {
            "trace_id": trace_id,
            "span_id": span_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "prompt": redacted_prompt[:100] + ("..." if len(redacted_prompt) > 100 else ""),
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": 0,
            "total_tokens": prompt_tokens,
            "tier_latencies_ms": {},
            "total_latency_ms": 0.0,
            "cost_usd": 0.0,
            "status": "IN_PROGRESS"
        }

    def record_tier_latency(self, trace: Dict[str, Any], tier_name: str, latency_ms: float):
        """Records sub-millisecond execution latency for a specific retrieval tier."""
        trace["tier_latencies_ms"][tier_name] = round(latency_ms, 2)
        TIER_LATENCY_MS.labels(tier=tier_name).observe(latency_ms)

    def finalize_trace(self, trace: Dict[str, Any], output_text: str, total_latency_ms: float) -> Dict[str, Any]:
        """Finalizes trace span with completion tokens, cost, and total latency."""
        completion_tokens = self.estimate_tokens(output_text)
        total_tokens = trace["prompt_tokens"] + completion_tokens
        cost_usd = self.calculate_cost(trace["model"], trace["prompt_tokens"], completion_tokens)

        trace["completion_tokens"] = completion_tokens
        trace["total_tokens"] = total_tokens
        trace["total_latency_ms"] = round(total_latency_ms, 2)
        trace["cost_usd"] = cost_usd
        trace["status"] = "COMPLETED"

        self.trace_history.append(trace)
        TRACES_TOTAL.labels(model=trace["model"]).inc()
        TOKENS_TOTAL.labels(model=trace["model"]).inc(total_tokens)
        COST_USD_TOTAL.labels(model=trace["model"]).inc(cost_usd)
        TOTAL_LATENCY_MS.observe(total_latency_ms)
        logger.info(f"Trace Completed: [{trace['trace_id']}] Latency: {trace['total_latency_ms']}ms | Tokens: {total_tokens} | Cost: ${cost_usd:.6f}")
        return trace

    def export_telemetry_dashboard(self) -> Dict[str, Any]:
        """
        Exports a JSON summary of this instance's own recent trace history --
        a debugging/demo view scoped to one process (or, for the MCP server
        specifically, one HybridRAGRetriever call, since a fresh instance is
        constructed per call). For real cross-call metrics, scrape the module-
        level Prometheus objects above via /metrics on the MCP sidecar (see
        `mcp_server/financial_data_mcp_server.py`), not this method.
        """
        total_calls = len(self.trace_history)
        if total_calls == 0:
            return {"total_calls": 0, "status": "No traces recorded."}

        total_tokens = sum(t["total_tokens"] for t in self.trace_history)
        total_cost = sum(t["cost_usd"] for t in self.trace_history)
        avg_latency = round(sum(t["total_latency_ms"] for t in self.trace_history) / total_calls, 2)

        tier_avg_latencies = {}
        all_tiers = set()
        for t in self.trace_history:
            all_tiers.update(t["tier_latencies_ms"].keys())

        for tier in all_tiers:
            lats = [t["tier_latencies_ms"][tier] for t in self.trace_history if tier in t["tier_latencies_ms"]]
            tier_avg_latencies[tier] = round(sum(lats) / len(lats), 2) if lats else 0.0

        # self.trace_history is a bounded deque (see MAX_TRACE_HISTORY above),
        # which doesn't support slicing -- materialize to a list first.
        recent = list(self.trace_history)[-5:]
        return {
            "total_llm_calls": total_calls,
            "total_tokens_processed": total_tokens,
            "cumulative_cost_usd": round(total_cost, 6),
            "average_latency_ms": avg_latency,
            "tier_latency_breakdown_ms": tier_avg_latencies,
            "active_traces": [t["trace_id"] for t in recent]
        }

def main():
    telemetry = LLMOpsTelemetry()
    print("🚀 Verifying LLMOps Telemetry & Observability Engine...")
    print("======================================================")

    # Simulate AI Trace Workflow
    prompt = "Identify overdrawn deposit account customer risk exposure and master party entities"
    trace = telemetry.start_trace(prompt, model="ollama/gemma4")

    # Simulate tier latencies
    time.sleep(0.05)
    telemetry.record_tier_latency(trace, "Vector_Search_pgvector", 42.1)
    telemetry.record_tier_latency(trace, "Graph_RAG_Neo4j", 12.8)
    telemetry.record_tier_latency(trace, "Semantic_Metrics_Cubejs", 6.2)
    telemetry.record_tier_latency(trace, "Relational_SQL_PostgreSQL", 8.4)

    output = "Found 12 overdrawn deposit accounts associated with High-AML risk customer profile P-92841."
    final_trace = telemetry.finalize_trace(trace, output, total_latency_ms=69.5)

    print("\n1. Individual Trace Span Record:")
    print(json.dumps(final_trace, indent=2))

    # Export Dashboard
    dashboard = telemetry.export_telemetry_dashboard()
    print("\n2. Aggregate Telemetry Dashboard:")
    print(json.dumps(dashboard, indent=2))

    print("\n✅ LLMOps Telemetry & Observability Engine Verification Complete!")

if __name__ == "__main__":
    main()
