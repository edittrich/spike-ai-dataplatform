#!/usr/bin/env python3
"""
===============================================================================
Unified Agentic Evaluation Benchmark & RAG Triad Verification Suite
===============================================================================
Evaluates accuracy, precision, latency, and RAG Triad metrics across Cluster 2:
1. Vector Semantic Search (pgvector 0.8.0 HNSW & 2-Stage Re-Ranking)
2. Knowledge Graph Traversal (Neo4j Cypher & Dynamic Text-to-Cypher)
3. Semantic Layer Metric Aggregation (Cube.js REST API)
4. Relational Database SQL (Supabase PostgreSQL)
5. FastMCP Agentic Tool Execution & RAG Triad Quality Benchmarks
===============================================================================
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import re
import time
import asyncio
from mcp_server.financial_data_mcp_server import mcp
from scripts.hybrid_rag_retriever import HybridRAGRetriever
from scripts.rag_triad_evaluator import RAGTriadEvaluator
from scripts.llm_judge_evaluator import LLMJudgeEvaluator

class AgenticEvaluator:
    def __init__(self):
        self.retriever = HybridRAGRetriever()
        self.triad_evaluator = RAGTriadEvaluator()
        # Phase 4 (hardening plan, Q7): a real local Ollama model judges
        # faithfulness/relevance semantically instead of by token overlap --
        # see llm_judge_evaluator.py's module docstring for the exact defect
        # this fixes (empty response scoring 1.0, digit-substring "grounding").
        # Checked once here (not per-scenario) since is_available() does a
        # real network round-trip; every scenario shares this one result.
        self.llm_judge = LLMJudgeEvaluator()
        self.llm_judge_available = self.llm_judge.is_available()
        if self.llm_judge_available:
            print(f"🧑‍⚖️  LLM-as-judge scoring enabled (Ollama model: {self.llm_judge.model}).")
        else:
            print("⚠️  LLM-as-judge unavailable (Ollama unreachable or model not pulled) -- "
                  "falling back to RAGTriadEvaluator's substring-based scorer for this run.")
        self.benchmark_results = []

    def score_triad(self, prompt: str, context_text: str, response_text: str):
        """Tries the real LLM judge first (Q7's fix); falls back to the
        substring scorer if the judge is unavailable or fails for this one
        call specifically (e.g. a transient Ollama timeout) -- fail open per
        llm_judge_evaluator.py's documented contract, not fail the whole
        benchmark run over one optional scorer."""
        if self.llm_judge_available:
            judged = self.llm_judge.evaluate_triad(prompt, context_text, response_text)
            if judged is not None:
                return judged
        fallback = self.triad_evaluator.evaluate_triad(prompt, context_text, response_text)
        fallback["judge_mode"] = "substring_fallback"
        fallback["judge_model"] = None
        return fallback

    async def run_benchmark_suite(self):
        print("🚀 Starting Cluster 2 Agentic Evaluation Benchmark & RAG Triad Suite...")
        print("=======================================================================")

        # Scenario 1: AML & Customer Exposure Audit
        await self.evaluate_scenario_1()

        # Scenario 2: Semantic Layer Liquidity Metric Verification
        await self.evaluate_scenario_2()

        # Scenario 3: Credit Risk & Collateral Traversal
        await self.evaluate_scenario_3()

        # Scenario 4: Data Quality & Governance SLA Check
        await self.evaluate_scenario_4()

        # Scenario 5: End-to-End MCP Tool Orchestration
        await self.evaluate_scenario_5()

        return self.print_summary_report()

    async def evaluate_scenario_1(self):
        print("\n📋 Benchmark 1: High-Risk AML & Overdrawn Customer Exposure Inquiry")
        start_time = time.time()
        prompt = "Identify overdrawn deposit account customer risk exposure and master party entities"
        payload = self.retriever.hybrid_retrieve(prompt)
        elapsed_ms = round((time.time() - start_time) * 1000, 2)

        # Assertions
        vector_match = any(any(k in v["display_name"] for k in ["party", "deposit", "overdraft", "account"]) for v in payload["vector_schema_context"])
        # Q2 (Phase 3, already fixed elsewhere) changed relational_sql_context
        # from a list[str] to list[dict] (real Python values, no more pipe-
        # delimited text parsing) -- this benchmark script was never updated
        # to match, so `"INDIVIDUAL" in line` silently checked dict *keys*
        # (always False, a false-negative rather than a crash) and the triad
        # context line below crashed outright on `" ".join(...)` over dicts.
        # Both fixed by stringifying each row instead of assuming str rows.
        sql_match = any("INDIVIDUAL" in json.dumps(row) for row in payload["relational_sql_context"])
        score = 100 if (vector_match and sql_match) else 50

        # RAG Triad Evaluation
        context_str = json.dumps(payload["vector_schema_context"]) + " " + json.dumps(payload["relational_sql_context"])
        response_str = "Found overdrawn deposit account customer risk exposure under party_individual and deposit_overdraft_facility."
        triad_metrics = self.score_triad(prompt, context_str, response_str)

        self.record_result("AML & Overdrawn Risk Exposure", score, elapsed_ms, triad_metrics, {
            "Vector Schema Matched": vector_match,
            "PostgreSQL SQL Executed": sql_match
        })

    async def evaluate_scenario_2(self):
        print("\n📋 Benchmark 2: Semantic Layer Liquidity Metric Calculation")
        start_time = time.time()
        prompt = "Query total available balance deposit liquidity metric from semantic layer"
        res_metrics = await mcp.call_tool("query_semantic_metrics", {
            "cube_name": "deposit_balance",
            "measures": ["total_available_balance"]
        })
        elapsed_ms = round((time.time() - start_time) * 1000, 2)

        res_str = str(res_metrics)
        # Extract the actual returned value rather than asserting equality
        # against one golden run's exact figure (previously a hardcoded
        # "63542607.6400" in res_str check) -- that passed only because
        # generate_synthetic_data.py seeds with a fixed random.seed(42); any
        # change to the seed data made this "benchmark" fail with no
        # diagnostic. A real positive number is what the assertion cares about.
        match = re.search(r'"deposit_balance\.total_available_balance"\s*:\s*"?(-?\d+(?:\.\d+)?)', res_str)
        metric_value = float(match.group(1)) if match else None
        metric_val_present = metric_value is not None and metric_value > 0
        score = 100 if metric_val_present else 0

        # RAG Triad Evaluation, against the value actually returned -- not a
        # hardcoded figure repeated into the "context" to guarantee a match.
        context_str = f"cube deposit_balance measure total_available_balance {metric_value if metric_value is not None else 'N/A'}"
        triad_metrics = self.score_triad(prompt, context_str, res_str)

        self.record_result("Cube.js Semantic Metric (total_available_balance)", score, elapsed_ms, triad_metrics, {
            "Total Available Balance Returned": f"${metric_value:,.2f}" if metric_value is not None else "N/A"
        })

    async def evaluate_scenario_3(self):
        print("\n📋 Benchmark 3: Credit Risk & Pledged Collateral Graph Traversal")
        start_time = time.time()
        prompt = "Traverse credit risk and loan agreement pledged collateral assets in knowledge graph"
        cypher = """
        MATCH (l:LoanAgreement)-[r:SECURED_BY]->(c:LoanCollateral)
        RETURN l.agreement_number AS loan_ref, l.principal_amount AS principal, c.collateral_type AS collateral, c.estimated_value AS valuation
        LIMIT 5;
        """
        res_graph = await mcp.call_tool("query_knowledge_graph", {"cypher_query": cypher})
        elapsed_ms = round((time.time() - start_time) * 1000, 2)

        res_str = str(res_graph)
        graph_matched = len(res_str) > 0 and "Cypher Execution Error" not in res_str
        score = 100 if graph_matched else 0

        # No RAG Triad metrics: this checks that the tool executed and
        # returned data, not a generated answer's faithfulness to retrieved
        # context. Passing the same string as both context and response (the
        # previous code) makes faithfulness 1.0 by construction -- there's no
        # separately-generated answer here to actually evaluate.
        self.record_result("Neo4j Knowledge Graph Multi-Hop Traversal", score, elapsed_ms, None, {
            "Loan Collateral Graph Path Traversed": graph_matched,
            "Benchmark Prompt": prompt,
        })

    async def evaluate_scenario_4(self):
        print("\n📋 Benchmark 4: OpenMetadata Data Quality & SLA Scorecard Assertion")
        start_time = time.time()
        prompt = "Check data quality assertions and SLA scorecard for table deposit_account"
        res_dq = await mcp.call_tool("check_data_quality", {"table_name": "deposit_account"})
        elapsed_ms = round((time.time() - start_time) * 1000, 2)

        res_str = str(res_dq)
        dq_matched = "Not Null Assertion" in res_str or "Success" in res_str
        score = 100 if dq_matched else 0

        # No RAG Triad metrics -- see the note in evaluate_scenario_3.
        self.record_result("Data Quality & Governance SLA Scorecard", score, elapsed_ms, None, {
            "OpenMetadata 59 Assertion Suite Checked": dq_matched,
            "Benchmark Prompt": prompt,
        })

    async def evaluate_scenario_5(self):
        print("\n📋 Benchmark 5: End-to-End MCP Tool Orchestration & Multi-Modal Search")
        start_time = time.time()
        prompt = "Search data catalog for table party_individual and column metadata"
        res_catalog = await mcp.call_tool("search_data_catalog", {"query": "party_individual"})
        elapsed_ms = round((time.time() - start_time) * 1000, 2)

        res_str = str(res_catalog)
        catalog_matched = "party_individual" in res_str
        score = 100 if catalog_matched else 0

        # No RAG Triad metrics -- see the note in evaluate_scenario_3.
        self.record_result("FastMCP Data Catalog Tool Call (`search_data_catalog`)", score, elapsed_ms, None, {
            "OpenMetadata Search Index Queried": catalog_matched,
            "Benchmark Prompt": prompt,
        })

    def record_result(self, name, score, latency_ms, triad_metrics, details):
        status = "PASSED" if score >= 80 else "FAILED"
        self.benchmark_results.append({
            "scenario": name,
            "score": score,
            "status": status,
            "latency_ms": latency_ms,
            "triad_metrics": triad_metrics,
            "details": details
        })
        if triad_metrics:
            triad_note = f" — Triad Score: {triad_metrics['triad_score_percent']} ({triad_metrics.get('judge_mode', 'unknown')})"
        else:
            triad_note = " — Triad: N/A (execution check only, no generated response to evaluate)"
        print(f"  Result: [{status}] Score: {score}% — Latency: {latency_ms}ms{triad_note}")

    def print_summary_report(self):
        print("\n=======================================================")
        print("📊 CLUSTER 2 AGENTIC EVALUATION & RAG TRIAD SUMMARY")
        print("=======================================================")

        total_tests = len(self.benchmark_results)
        if total_tests == 0:
            print("No benchmark results recorded.")
            return

        passed_tests = sum(1 for r in self.benchmark_results if r["status"] == "PASSED")
        avg_score = round(sum(r["score"] for r in self.benchmark_results) / total_tests, 2)
        avg_latency = round(sum(r["latency_ms"] for r in self.benchmark_results) / total_tests, 2)

        # Only scenarios with a genuinely separate generated response get a
        # RAG Triad score (see the per-scenario notes above) -- averaging in
        # execution-only checks (triad_metrics=None) would silently pad the
        # average with meaningless perfect scores.
        triad_results = [r for r in self.benchmark_results if r["triad_metrics"]]
        avg_triad = (
            round(sum(r["triad_metrics"]["triad_composite_score"] for r in triad_results) / len(triad_results), 4)
            if triad_results else None
        )

        print(f"Total Test Scenarios:     {total_tests}")
        print(f"Passed Scenarios:         {passed_tests} / {total_tests} ({round(passed_tests/total_tests*100, 1)}%)")
        print(f"Average Accuracy Score:   {avg_score}%")
        print(f"Average Latency:          {avg_latency}ms")
        if avg_triad is not None:
            print(f"Average RAG Triad Score:  {round(avg_triad * 100, 1)}% (from {len(triad_results)}/{total_tests} scenarios with a real generated response -- see table below)")
        print("-------------------------------------------------------")

        print("\n🎯 Scenario Quality Breakdown & RAG Triad Scorecard Table:")
        print(f"{'Scenario':<42} | {'Status':<6} | {'Accuracy':<8} | {'Context Rel':<11} | {'Faithful':<8} | {'Ans Rel':<8} | {'Triad':<6} | {'Judge Mode':<24}")
        print("-" * 135)
        for r in self.benchmark_results:
            tm = r["triad_metrics"]
            scen = r['scenario'][:40]
            if tm:
                print(f"{scen:<42} | {r['status']:<6} | {r['score']}%     | {tm['context_relevance']*100:5.1f}%      | {tm['faithfulness']*100:5.1f}%   | {tm['answer_relevance']*100:5.1f}%   | {tm['triad_score_percent']:<6} | {tm.get('judge_mode', 'unknown'):<24}")
            else:
                print(f"{scen:<42} | {r['status']:<6} | {r['score']}%     | {'N/A':<11}  | {'N/A':<8} | {'N/A':<8} | {'N/A':<6} | {'N/A':<24}")

        print(f"\nBenchmark run complete: {passed_tests}/{total_tests} scenarios passed (score >= 80%).")
        return passed_tests == total_tests

if __name__ == "__main__":
    # Q7 (hardening plan): "evaluate_agentic_retrieval.py still doesn't call
    # sys.exit(1) on a failed run, unlike the E2E script (Q8), which does."
    # A benchmark with a real failing scenario previously still exited 0 --
    # indistinguishable from a clean run to any CI job or script checking
    # `$?`, silently masking a real regression.
    evaluator = AgenticEvaluator()
    all_passed = asyncio.run(evaluator.run_benchmark_suite())
    sys.exit(0 if all_passed else 1)
