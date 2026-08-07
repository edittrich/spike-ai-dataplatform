#!/usr/bin/env python3
"""
===============================================================================
Enterprise Model Context Protocol (MCP) Server for AI Agents
===============================================================================
Exposes standardized MCP tools, context resources, and data prompts
to autonomous AI agents (Antigravity, Gemini, Claude, Cursor, etc.) via FastMCP.

Exposed MCP Tools:
1. `search_data_catalog`: OpenMetadata catalog & FIBO URI search.
2. `query_semantic_metrics`: Cube.js open-source semantic metrics query.
3. `query_knowledge_graph`: Neo4j Cypher Graph-RAG query execution.
4. `query_financial_database`: Supabase PostgreSQL read-only SQL query.
5. `check_data_quality`: OpenMetadata real-time assertion scorecards.
6. `hybrid_rag_search`: 4-Tier Hybrid RAG context search.
===============================================================================
"""

import hmac
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

import psycopg2
import uvicorn
from neo4j import READ_ACCESS, GraphDatabase
from starlette.responses import JSONResponse

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from fastmcp import FastMCP

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this module is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env
from scripts.ai_safety_guardrails import AISafetyGuardrails

# Loads .env for the stdio case (this file run directly on the host, e.g. as an
# AI client's MCP server command -- see README's client integration example). A
# no-op inside the mcp_sidecar container, where docker-compose.yml's
# `environment:` block already injects real values and `override=False` means
# they're never replaced by anything (or lack of anything) in a mounted `.env`.
load_env()

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("FinancialDataMCPServer")

# Initialize FastMCP Server
mcp = FastMCP("Enterprise-Financial-Data-Platform")
guardrails = AISafetyGuardrails()

# Environment Configuration
OPENMETADATA_URL = os.getenv("OPENMETADATA_URL", "http://127.0.0.1:8585/api/v1")
CUBEJS_URL = os.getenv("CUBEJS_URL", "http://127.0.0.1:4000/cubejs-api/v1/load")
JWT_TOKEN = os.getenv("OPENMETADATA_JWT_TOKEN", "")
if not JWT_TOKEN:
    logger.warning(
        "OPENMETADATA_JWT_TOKEN is not set; OpenMetadata API calls will be unauthenticated."
    )

CUBEJS_API_SECRET = os.getenv("CUBEJS_API_SECRET", "")
if not CUBEJS_API_SECRET:
    logger.warning(
        "CUBEJS_API_SECRET is not set; query_semantic_metrics calls to Cube.js will be unauthenticated "
        "and will be rejected once Cube.js's own checkAuth enforcement is enabled."
    )

NEO4J_PASSWORD_CONFIGURED = bool(os.getenv("NEO4J_PASSWORD", ""))
if not NEO4J_PASSWORD_CONFIGURED:
    logger.warning(
        "NEO4J_PASSWORD is not set; query_knowledge_graph calls to Neo4j will likely fail authentication."
    )

# Native driver connection settings. This server previously shelled out to
# `docker exec <container> psql/cypher-shell`, which only works when the
# process has the `docker` CLI and a mounted docker.sock -- neither is true
# for the mcp_sidecar container this actually runs in, so query_financial_database,
# query_knowledge_graph, and hybrid_rag_search all failed with a
# FileNotFoundError the moment they were called over the real SSE endpoint.
# Mounting docker.sock would fix that but grants root-equivalent host access
# (container breakout risk); native drivers avoid that trade-off entirely.
#
# Connects as `mcp_readonly` (supabase/migrations/20260807151500_create_mcp_readonly_role.sql),
# not the `postgres` superuser -- as a non-superuser role it cannot call
# pg_read_file/lo_import/dblink or COPY ... TO/FROM PROGRAM, so a query that
# slips past scripts/ai_safety_guardrails.py's keyword scan still can't read
# the filesystem or run an OS command; it also holds no privileges outside the
# financial/ref schemas. Configure its password once via
# `python3 scripts/configure_readonly_role.py` after the migration has been applied.
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "54322"))
POSTGRES_USER = os.getenv("MCP_PG_READONLY_USER", "mcp_readonly")
POSTGRES_PASSWORD = os.getenv("MCP_PG_READONLY_PASSWORD", "")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")
if not POSTGRES_PASSWORD:
    logger.warning(
        "MCP_PG_READONLY_PASSWORD is not set; query_financial_database and "
        "hybrid_rag_search's SQL tier will fail authentication until "
        "`python3 scripts/configure_readonly_role.py` has been run with it set."
    )

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# Shared-secret bearer token required to reach this server over SSE (see main()).
# Unset by default so a fresh checkout fails closed rather than silently exposing
# arbitrary SQL/Cypher execution over the network.
MCP_API_KEY = os.getenv("MCP_API_KEY", "")

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {JWT_TOKEN}"
}

# Row cap applied via cursor.fetchmany() rather than fetchall() + slicing --
# query_financial_database previously had no limit at all, so a broad SELECT
# both fetched and returned an unbounded number of rows into the LLM context.
MAX_SQL_RESULT_ROWS = 200

def query_pg(sql: str) -> str:
    """
    Execute a SQL query against PostgreSQL over a native driver connection.
    Output format matches the previous `psql -t -A` behavior (no header,
    pipe-delimited fields) for compatibility with existing callers.
    """
    conn = psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT, user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, dbname=POSTGRES_DB,
        # Defense in depth independent of the mcp_readonly role's own
        # session-level defaults (set by the role-creation migration) -- these
        # apply even against a deployment that hasn't run that migration yet.
        options="-c statement_timeout=10000 -c idle_in_transaction_session_timeout=30000",
    )
    try:
        # Defense in depth: even if a mutation slipped past the guardrails'
        # keyword check, the database itself now refuses to execute it. (The
        # mcp_readonly role's own privileges are the primary control -- see the
        # comment above POSTGRES_USER -- this transaction-level flag is a second
        # layer on top of that.)
        conn.set_session(readonly=True)
        with conn.cursor() as cur:
            cur.execute(sql)
            if cur.description is None:
                return ""
            rows = cur.fetchmany(MAX_SQL_RESULT_ROWS)
            return "\n".join(
                "|".join("" if v is None else str(v) for v in row) for row in rows
            )
    finally:
        conn.close()

def query_neo4j(cypher: str) -> str:
    """
    Execute a Cypher query against Neo4j over the native bolt driver. Output
    format matches the previous `cypher-shell` behavior (a header line of
    column names, followed by one comma-joined line per record) for
    compatibility with existing callers.
    """
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        # Neo4j Community Edition (this platform's neo4j:5.18.0-community image)
        # has no custom-role RBAC to restrict this connection to read-only the
        # way mcp_readonly does for Postgres -- READ_ACCESS mode is the
        # equivalent enforcement available here: the server rejects any write
        # clause (CREATE/SET/DELETE/MERGE/REMOVE/...) inside a transaction opened
        # this way, independent of scripts/ai_safety_guardrails.py's keyword
        # scan. It does NOT block procedure calls that don't write to the graph
        # (e.g. an APOC HTTP-fetch procedure used for SSRF) -- that's covered by
        # the guardrail's Cypher keyword list and by restricting the APOC
        # plugin's allowlist in docker-compose.yml instead.
        with driver.session(default_access_mode=READ_ACCESS) as session:
            result = session.run(cypher)
            keys = list(result.keys())
            lines = [", ".join(keys)]
            for record in result:
                lines.append(", ".join(str(record[k]) for k in keys))
            return "\n".join(lines)
    finally:
        driver.close()


class BearerAuthMiddleware:
    """
    Minimal ASGI middleware enforcing a static bearer token on every request.

    FastMCP's SSE transport has no built-in authentication; without this, the
    mcp_sidecar container (network_mode: host) exposes arbitrary SQL/Cypher
    execution tools to anything that can reach the host on the network.
    """

    def __init__(self, app, api_key: str):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        auth_header = headers.get(b"authorization", b"")
        token = auth_header[7:] if auth_header.startswith(b"Bearer ") else b""
        # Compare as bytes, not str: hmac.compare_digest raises TypeError (not a
        # timing-safe False) when given a str containing a non-ASCII character --
        # e.g. `Authorization: Bearer \xc3\xbc...` previously turned into an
        # unhandled 500 instead of a 401, no worse than a plain string
        # comparison here in terms of information leaked, but a crash where a
        # clean rejection was intended.
        if not token or not hmac.compare_digest(token, self.api_key.encode("utf-8")):
            response = JSONResponse({"error": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

# -----------------------------------------------------------------------------
# MCP TOOLS
# -----------------------------------------------------------------------------

@mcp.tool()
def search_data_catalog(query: str) -> str:
    """
    Search OpenMetadata Enterprise Catalog for tables, column metadata,
    data products, and W3C FIBO ontology class URIs.
    """
    logger.info(f"Executing search_data_catalog tool query: '{query}'")
    url = f"{OPENMETADATA_URL}/search/query?q={urllib.parse.quote(query)}&index=table_search_index&size=5"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            hits = data.get("hits", {}).get("hits", [])
            results = []
            for h in hits:
                src = h.get("_source", {})
                results.append({
                    "name": src.get("name"),
                    "fqn": src.get("fullyQualifiedName"),
                    "description": src.get("description", "")[:200],
                    "tags": [t.get("tagFQN") for t in src.get("tags", [])]
                })
            return json.dumps(results, indent=2)
    except Exception as e:
        logger.error(f"Catalog search error: {e}")
        # Surface the real failure instead of a fabricated catalog hit — a
        # synthesized result here would be indistinguishable from real data
        # to a calling LLM agent, masking outages/auth failures as success.
        return f"Catalog Search Error: {e}"

@mcp.tool()
def query_semantic_metrics(cube_name: str, measures: List[str]) -> str:
    """
    Query Cube.js open-source semantic layer for standardized metrics and KPIs
    (e.g., cube_name='deposit_balance', measures=['total_available_balance']).
    """
    logger.info(f"Executing query_semantic_metrics tool for cube '{cube_name}' measures {measures}")
    query_body = {"measures": [f"{cube_name}.{m}" for m in measures]}
    url_encoded = urllib.parse.quote(json.dumps(query_body))
    url = f"{CUBEJS_URL}?query={url_encoded}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {CUBEJS_API_SECRET}"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return json.dumps(data.get("data", []), indent=2)
    except Exception as e:
        logger.error(f"Semantic metric query error: {e}")
        return f"Error querying semantic layer: {e}"

@mcp.tool()
def query_knowledge_graph(cypher_query: str) -> str:
    """
    Execute multi-hop Cypher queries on Neo4j Knowledge Graph database
    to traverse entity relationships (:Party, :Individual, :Customer, :DepositAccount, :LoanAgreement).
    """
    logger.info("Executing query_knowledge_graph tool")
    safe, reason = guardrails.validate_read_only_query(cypher_query, "Cypher")
    if not safe:
        logger.warning(f"Blocked unsafe Cypher query: {reason}")
        return reason
    try:
        raw = query_neo4j(cypher_query)
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        return "\n".join(lines[:10])
    except Exception as e:
        logger.error(f"Cypher execution error: {e}")
        return f"Cypher Execution Error: {e}"

@mcp.tool()
def query_financial_database(sql_query: str) -> str:
    """
    Execute read-only SQL queries on Supabase PostgreSQL database schemas (`ref` and `financial`).
    """
    logger.info("Executing query_financial_database tool")
    safe, reason = guardrails.validate_read_only_query(sql_query, "SQL")
    if not safe:
        logger.warning(f"Blocked unsafe SQL query: {reason}")
        return reason
    try:
        raw = query_pg(sql_query)
        return raw if raw else "No records returned."
    except Exception as e:
        logger.error(f"SQL execution error: {e}")
        return f"SQL Query Error: {e}"

@mcp.tool()
def check_data_quality(table_name: str) -> str:
    """
    Fetch real-time OpenMetadata Data Quality test suite assertions, scorecards, and SLAs.
    """
    logger.info(f"Executing check_data_quality tool for table '{table_name}'")
    url = f"{OPENMETADATA_URL}/dataQuality/testCases?limit=20&fields=testCaseResult"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            test_cases = data.get("data", [])
            matched = [tc for tc in test_cases if table_name.lower() in tc.get("entityFQN", "").lower()]
            results = []
            for tc in matched:
                res = tc.get("testCaseResult", {})
                results.append({
                    "test_name": tc.get("displayName"),
                    "status": res.get("testCaseStatus"),
                    "result_message": res.get("result")
                })
            return json.dumps(results, indent=2) if results else f"No active data quality assertions for {table_name}."
    except Exception as e:
        logger.error(f"Data quality check error: {e}")
        # Surface the real failure instead of a fabricated "Success" assertion
        # — a broken data-quality subsystem must not look like it's passing.
        return f"Data Quality Check Error: {e}"

@mcp.tool()
def hybrid_rag_search(prompt: str) -> str:
    """
    Execute full 4-tier Hybrid RAG context search (Vector Search + Cypher + Cube.js Metrics + SQL)
    for complex natural language questions.
    """
    logger.info(f"Executing hybrid_rag_search tool for prompt: '{prompt}'")
    from scripts.hybrid_rag_retriever import HybridRAGRetriever
    retriever = HybridRAGRetriever()
    payload = retriever.hybrid_retrieve(prompt)
    return json.dumps(payload, indent=2)

# -----------------------------------------------------------------------------
# MCP RESOURCES
# -----------------------------------------------------------------------------

@mcp.resource("financial://catalog/schema")
def get_catalog_schema_resource() -> str:
    """Provides full documentation of PostgreSQL schemas `ref` and `financial`."""
    return """
    PostgreSQL Database Schemas:
    1. `financial.party`: Core BIAN/FIBO Master Party Entity (Party ID, Party BK, Status).
    2. `financial.party_individual`: Individual Person demographics (Name, DOB, PII).
    3. `financial.party_organization`: Legal corporate entities (Legal Name, Reg Number).
    4. `financial.party_role_customer`: Verified Customer Role & KYC Profiles.
    5. `financial.deposit_account`: BIAN Current & Savings Deposit Accounts.
    6. `financial.deposit_balance`: Real-Time Position Balances & Overdraft Exposures.
    7. `financial.loan_agreement`: Approved Loan Principal Contracts & Interest Rates.
    8. `financial.loan_collateral`: Pledged Asset Valuations (Real Estate, Vehicle, Cash).
    """

@mcp.resource("financial://data-contracts/slas")
def get_data_contracts_slas_resource() -> str:
    """Provides formal Data Contract SLA specifications for enterprise data products."""
    return """
    Data Product SLAs:
    - Party & Customer Data Product: Freshness 15m, Availability 99.9%, Quality Threshold >= 99.0%.
    - Deposit & Liquidity Data Product: Freshness 5m, Availability 99.95%, Quality Threshold >= 99.5%.
    - Loan & Credit Risk Data Product: Freshness 1h, Availability 99.9%, Quality Threshold >= 99.0%.
    """

def main():
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    port = int(os.getenv("MCP_PORT", "8001"))
    # Defaults to loopback-only, not 0.0.0.0 -- this server executes arbitrary
    # (guardrail-checked) SQL/Cypher; binding every interface should be an
    # explicit choice (set MCP_HOST=0.0.0.0 in .env), not the out-of-the-box
    # behavior. docker-compose.yml's mcp_sidecar runs with network_mode: host,
    # so "loopback" there means the *host's* loopback -- reachable from the
    # host itself, not from the network.
    host = os.getenv("MCP_HOST", "127.0.0.1")
    if transport == "sse":
        if not MCP_API_KEY:
            # Fail closed, not open: this server previously logged a warning and
            # started anyway, serving SQL/Cypher execution tools unauthenticated
            # to anything that could reach the port. A misconfigured deployment
            # should refuse to start, not silently drop its only access control.
            logger.error(
                "MCP_API_KEY is not set. Refusing to start the SSE endpoint "
                "unauthenticated -- set MCP_API_KEY in .env, or run with "
                "MCP_TRANSPORT=stdio if you don't need the network endpoint."
            )
            sys.exit(1)
        app = BearerAuthMiddleware(mcp.sse_app(), MCP_API_KEY)
        print(f"🚀 Launching Enterprise FastMCP Server (SSE HTTP Transport on http://{host}:{port})...")
        uvicorn.run(app, host=host, port=port, log_level="info")
    else:
        mcp.run()

if __name__ == "__main__":
    main()
