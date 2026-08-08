#!/usr/bin/env python3
"""
===============================================================================
Enterprise MCP Server Automated Verification Test Client
===============================================================================
Tests FastMCP tool registrations, schema resources, and execution handlers
to ensure 100% compliance with Model Context Protocol (MCP) standards.

Unlike a live-stack integration test, this asserts what's verifiable without
Postgres/Neo4j/OpenMetadata/Cube.js running (as in CI): tool/resource
registration is exactly what's documented, and every tool call executes
without an unhandled exception and returns non-empty text — whether that
text is real data or a downstream "X Error: ..." message (expected when the
stack is down) is not itself a failure. A tool crashing, disappearing from
registration, or returning nothing at all IS a failure and exits non-zero,
so this suite can actually fail — see docs/APPLICATION_RUNBOOK.md and the
platform security audit for why that mattered.
===============================================================================
"""

import asyncio
import sys

from mcp_server.financial_data_mcp_server import mcp

EXPECTED_TOOLS = {
    "search_data_catalog",
    "query_semantic_metrics",
    "query_knowledge_graph",
    "query_financial_database",
    "check_data_quality",
    "hybrid_rag_search",
}

EXPECTED_RESOURCES = {
    "financial://catalog/schema",
    "financial://data-contracts/slas",
}

failures = []


def check(condition: bool, description: str) -> None:
    status = "✅" if condition else "❌"
    print(f"   {status} {description}")
    if not condition:
        failures.append(description)


def extract_text(call_tool_result) -> str:
    """
    mcp.call_tool() returns (content_blocks, structured_result). Our tools
    return a single string, so structured_result['result'] holds it; fall
    back to the first content block's text if that shape ever changes.
    """
    _, structured = call_tool_result
    if isinstance(structured, dict) and "result" in structured:
        return str(structured["result"])
    content_blocks, _ = call_tool_result
    if content_blocks:
        return str(getattr(content_blocks[0], "text", content_blocks[0]))
    return ""


async def call_and_check(name: str, arguments: dict, label: str) -> None:
    try:
        result = await mcp.call_tool(name, arguments)
    except Exception as e:
        check(False, f"{label} raised an unhandled exception: {e}")
        return
    text = extract_text(result)
    print(f"      -> {text[:200]}{'...' if len(text) > 200 else ''}")
    check(bool(text.strip()), f"{label} returned non-empty text")


async def test_mcp_server():
    print("🚀 Verifying Enterprise FastMCP Server Tool Registrations...")
    print("------------------------------------------------------------")

    # 1. Registration checks — these don't need the live stack and catch the
    # exact class of regression (a tool silently disappearing, a resource
    # URI typo) that the old print-only version of this test could not.
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    print(f"📦 Discovered {len(tools)} Registered FastMCP Tools: {sorted(tool_names)}")
    check(tool_names == EXPECTED_TOOLS, f"exactly the 6 documented tools are registered (got {sorted(tool_names)})")

    resources = await mcp.list_resources()
    resource_uris = {str(r.uri) for r in resources}
    print(f"📦 Discovered {len(resources)} Registered FastMCP Resources: {sorted(resource_uris)}")
    check(resource_uris == EXPECTED_RESOURCES, f"exactly the 2 documented resources are registered (got {sorted(resource_uris)})")

    print("\n🧪 Testing FastMCP Tool Execution Handlers...")
    print("---------------------------------------------")

    print("\n1. `search_data_catalog('deposit_account')`:")
    await call_and_check("search_data_catalog", {"query": "deposit_account"}, "search_data_catalog")

    print("\n2. `query_semantic_metrics('deposit_balance', ['total_available_balance'])`:")
    await call_and_check(
        "query_semantic_metrics",
        {"cube_name": "deposit_balance", "measures": ["total_available_balance"]},
        "query_semantic_metrics",
    )

    print("\n3. `query_knowledge_graph(...)`:")
    cypher = "MATCH (l:LoanAgreement)-[:SECURED_BY]->(c:LoanCollateral) RETURN l.agreement_number, c.collateral_type LIMIT 2;"
    await call_and_check("query_knowledge_graph", {"cypher_query": cypher}, "query_knowledge_graph")

    print("\n4. `query_financial_database(...)`:")
    sql = "SELECT party_type, COUNT(*) FROM financial.party GROUP BY party_type;"
    await call_and_check("query_financial_database", {"sql_query": sql}, "query_financial_database")

    print("\n5. `check_data_quality('deposit_account')`:")
    await call_and_check("check_data_quality", {"table_name": "deposit_account"}, "check_data_quality")

    # Q9 in the hardening plan: "hybrid_rag_search is registration-checked but
    # never invoked." It's wrapped in try/except RuntimeError (see
    # financial_data_mcp_server.py) specifically so it degrades to a clean
    # error string rather than raising when the embedding model isn't
    # installed (as in CI) -- so it's safe to actually call here like every
    # other tool, instead of only checking its registration.
    print("\n6. `hybrid_rag_search('What is the AML risk rating for high-value customers?')`:")
    await call_and_check(
        "hybrid_rag_search",
        {"prompt": "What is the AML risk rating for high-value customers?"},
        "hybrid_rag_search",
    )

    print()
    if failures:
        print(f"❌ Enterprise FastMCP Server Tool Verification FAILED ({len(failures)} check(s) failed):")
        for f in failures:
            print(f"   - {f}")
        sys.exit(1)

    print("✅ Enterprise FastMCP Server Tool Verification Complete!")


if __name__ == "__main__":
    asyncio.run(test_mcp_server())
