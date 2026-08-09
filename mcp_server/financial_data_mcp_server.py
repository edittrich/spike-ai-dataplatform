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

import functools
import hmac
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Annotated, Dict, List, Optional

# Q10 (hardening plan): Field(description=...) on each tool parameter below
# feeds FastMCP's own JSON-Schema generation (mcp.list_tools(), verified live
# to include these descriptions in each tool's inputSchema) -- the single
# source of truth scripts/ollama_agentic_tool_runner.py's OLLAMA_TOOLS now
# derives from at runtime instead of hand-duplicating as a separate literal.
from pydantic import Field

import psycopg2
import psycopg2.pool
import uvicorn
from neo4j import READ_ACCESS, GraphDatabase
from opentelemetry.trace import Status, StatusCode
from prometheus_client import Counter, Histogram, start_http_server
from starlette.responses import JSONResponse

# Q11 (hardening plan): this used to fall back to the standalone `fastmcp`
# package on ImportError. The two are not interchangeable: under `mcp` 1.x,
# `@mcp.tool()` returns the raw function, which `scripts/ollama_agentic_tool_runner.py`
# relies on to call tools directly; under standalone `fastmcp` 2.x+, the same
# decorator returns a `FunctionTool` object and every one of those direct
# calls raises `TypeError: 'FunctionTool' object is not callable`. Verified
# live which package actually wins today (both were installed): `mcp` does,
# since it's tried first and always succeeds -- so the fallback branch was
# already dead code in practice, silently masking the real risk that a
# future dependency change (or a fresh install missing `mcp`) would switch
# to the incompatible API with no signal at all beyond a confusing
# TypeError deep in the agentic runner. Grepped the whole repo: nothing
# imports the standalone `fastmcp` package for anything else, so it's
# removed from requirements.txt/Dockerfile.mcp entirely rather than kept
# around as an unused fallback.
from mcp.server.fastmcp import FastMCP

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this module is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._contracts import render_sla_summary
from scripts._dotenv_boot import load_env
from scripts._json_safe import json_safe_row
from scripts.ai_safety_guardrails import AISafetyGuardrails

# Loads .env for the stdio case (this file run directly on the host, e.g. as an
# AI client's MCP server command -- see README's client integration example). A
# no-op inside the mcp_sidecar container, where docker-compose.yml's
# `environment:` block already injects real values and `override=False` means
# they're never replaced by anything (or lack of anything) in a mounted `.env`.
load_env()

# _otel_tracing reads OTEL_* env config at import time, so it must be
# imported after load_env() -- see its module docstring.
from scripts._otel_tracing import get_tracer  # noqa: E402

_tracer = get_tracer(__name__)

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("FinancialDataMCPServer")

# Initialize FastMCP Server
mcp = FastMCP("Enterprise-Financial-Data-Platform")
guardrails = AISafetyGuardrails()

# Per-tool call counters/duration, scraped over the real, always-on Prometheus
# endpoint this process serves via start_http_server() in main() (see below).
# This replaces scripts/telemetry_metrics_exporter_server.py, which ran as a
# *separate* container process that could never see traces from this one --
# it was seeded with random.uniform() fake data because there was no way to
# feed it anything real. These metrics are, by construction, only ever
# updated by an actual tool invocation.
TOOL_CALLS_TOTAL = Counter(
    "mcp_tool_calls_total", "Total MCP tool invocations.", ["tool", "outcome"]
)
TOOL_DURATION_MS = Histogram(
    "mcp_tool_duration_ms",
    "MCP tool execution duration, in milliseconds.",
    ["tool"],
    buckets=(5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000),
)


def track_tool_call(func):
    """Records a Prometheus call count (by outcome) and duration for a tool
    function, and now also wraps the call in a real OTel span exported via
    OTLP to the otel_collector service (Part 5 item 2 in the hardening
    plan) -- one instrumentation point, two real observability outputs,
    covering all 6 tools uniformly (not just hybrid_rag_search, which is
    the only one that separately produces its own child spans -- see
    scripts/llmops_telemetry.py -- nested under this one automatically:
    start_as_current_span() below puts this span into OTel's ambient
    context, and llmops_telemetry.start_trace() picks that up as its
    parent the same way any OTel-instrumented call in this process would,
    with no explicit wiring between the two modules needed).

    Applied as the innermost decorator (below @mcp.tool()) so FastMCP still
    introspects the original function's signature for its JSON schema --
    functools.wraps preserves __wrapped__, which inspect.signature() follows.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        outcome = "error"
        with _tracer.start_as_current_span(f"mcp.tool.{func.__name__}") as span:
            try:
                result = func(*args, **kwargs)
                outcome = "success"
                span.set_status(Status(StatusCode.OK))
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise
            finally:
                span.set_attribute("outcome", outcome)
                TOOL_CALLS_TOTAL.labels(tool=func.__name__, outcome=outcome).inc()
                TOOL_DURATION_MS.labels(tool=func.__name__).observe((time.perf_counter() - start) * 1000)
    return wrapper

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

# Module-level singletons, built lazily on first use and reused for the life
# of this process (Q6: query_pg used to open/close a new connection and
# query_neo4j used to construct/destroy an entire GraphDatabase.driver on
# every single call -- expensive and exactly the anti-pattern the neo4j
# driver's own docs warn against; a driver is meant to be built once per
# application and reused). A real connection pool (not a single shared
# connection) is used for Postgres specifically because this is a
# long-running server that may field concurrent tool calls -- one psycopg2
# connection is not safe for concurrent use by multiple threads, but the
# neo4j driver *is* thread-safe and pools internally, so a single shared
# driver instance is the correct, documented usage there.
_pg_pool: Optional["psycopg2.pool.ThreadedConnectionPool"] = None
_neo4j_driver = None


def _get_pg_pool():
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = psycopg2.pool.ThreadedConnectionPool(
            1, 5,
            host=POSTGRES_HOST, port=POSTGRES_PORT, user=POSTGRES_USER,
            password=POSTGRES_PASSWORD, dbname=POSTGRES_DB, connect_timeout=10,
            # Defense in depth independent of the mcp_readonly role's own
            # session-level defaults (set by the role-creation migration) --
            # these apply even against a deployment that hasn't run that
            # migration yet.
            options="-c statement_timeout=10000 -c idle_in_transaction_session_timeout=30000",
        )
    return _pg_pool


def _get_neo4j_driver():
    global _neo4j_driver
    if _neo4j_driver is None:
        _neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD), connection_timeout=10)
    return _neo4j_driver


def query_pg(sql: str, params=None) -> List[Dict]:
    """Execute a SQL query against PostgreSQL over a pooled native driver
    connection. Returns list[dict] (one dict per row, keyed by column name)
    instead of the pipe-delimited text the previous version reconstructed
    purely to keep callers' `.split("|")` parsing working -- see Q2: any
    column value containing a literal `|` shifted columns and raised
    ValueError out of the tool."""
    pool = _get_pg_pool()
    conn = pool.getconn()
    try:
        # Defense in depth: even if a mutation slipped past the guardrails'
        # keyword check, the database itself now refuses to execute it. (The
        # mcp_readonly role's own privileges are the primary control -- see the
        # comment above POSTGRES_USER -- this transaction-level flag is a second
        # layer on top of that.) Checked rather than unconditionally re-set on
        # every call: a connection checked back into the pool by a previous
        # caller already has autocommit=True, and set_session() requires no
        # transaction be in progress, which autocommit already guarantees --
        # but only setting it once per underlying connection avoids relying on
        # that ordering being preserved by every psycopg2 version.
        if not conn.autocommit:
            conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description is None:
                return []
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchmany(MAX_SQL_RESULT_ROWS)
            return [json_safe_row(dict(zip(columns, row))) for row in rows]
    finally:
        pool.putconn(conn)

def query_neo4j(cypher: str, params=None) -> List[Dict]:
    """Execute a Cypher query against Neo4j over the shared bolt driver.
    Returns list[dict] -- one dict per record, keyed by the Cypher query's
    own RETURN aliases (via neo4j's record.data())."""
    driver = _get_neo4j_driver()
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
        result = session.run(cypher, params or {})
        return [json_safe_row(record.data()) for record in result]


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
@track_tool_call
def search_data_catalog(
    query: Annotated[str, Field(description="Catalog search query (e.g. 'deposit_account', 'party')")],
) -> str:
    """
    Search OpenMetadata Enterprise Catalog for tables, column metadata,
    data products, and W3C FIBO ontology class URIs.
    """
    logger.info(f"Executing search_data_catalog tool query: '{query}'")
    url = f"{OPENMETADATA_URL}/search/query?q={urllib.parse.quote(query)}&index=table_search_index&size=5"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
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
@track_tool_call
def query_semantic_metrics(
    cube_name: Annotated[str, Field(description="Cube name (e.g. 'deposit_balance')")],
    measures: Annotated[List[str], Field(description="Measure names (e.g. ['total_available_balance'])")],
) -> str:
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
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return json.dumps(data.get("data", []), indent=2)
    except Exception as e:
        logger.error(f"Semantic metric query error: {e}")
        return f"Error querying semantic layer: {e}"

@mcp.tool()
@track_tool_call
def query_knowledge_graph(
    cypher_query: Annotated[
        str, Field(description="Cypher query string (e.g. 'MATCH (l:LoanAgreement) RETURN l LIMIT 5;')")
    ],
) -> str:
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
        # Capped at 10 records on the structured result itself, rather than
        # the previous version's `lines[:10]` slice of already-formatted text
        # (which only worked because each record happened to render as
        # exactly one line -- a record containing an embedded newline, e.g.
        # from a multi-line string property, would have silently truncated
        # mid-record instead).
        records = query_neo4j(cypher_query)[:10]
        # H6: this and query_financial_database were the two most powerful
        # tools with no output-side control at all -- a query returning
        # first_name/last_name/date_of_birth (etc.) passed the read-only
        # keyword check and returned unredacted PII to the calling agent;
        # only hybrid_rag_search sanitized anything. Field-aware redaction
        # by real property name (see AISafetyGuardrails.redact_row) instead
        # of guessing from value shape -- the same mechanism H2 uses to mask
        # Cube.js dimensions and H8's own recommended fix.
        redacted_records = guardrails.redact_rows(records)
        return json.dumps(redacted_records, indent=2) if redacted_records else "No records returned."
    except Exception as e:
        # H6: exception text used to be returned verbatim to the caller --
        # a driver error can embed hostnames, schema/table/column names, or
        # fragments of the query itself. Full detail still goes to the
        # server-side log; the caller gets a generic, non-identifying message.
        logger.error(f"Cypher execution error: {e}")
        return "Cypher Execution Error: the query could not be executed. See server logs for detail."

@mcp.tool()
@track_tool_call
def query_financial_database(
    sql_query: Annotated[str, Field(description="Read-only SQL SELECT query")],
) -> str:
    """
    Execute read-only SQL queries on Supabase PostgreSQL database schemas (`ref` and `financial`).
    """
    logger.info("Executing query_financial_database tool")
    safe, reason = guardrails.validate_read_only_query(sql_query, "SQL")
    if not safe:
        logger.warning(f"Blocked unsafe SQL query: {reason}")
        return reason
    try:
        rows = query_pg(sql_query)
        # H6: see query_knowledge_graph's identical comment above.
        redacted_rows = guardrails.redact_rows(rows)
        return json.dumps(redacted_rows, indent=2) if redacted_rows else "No records returned."
    except Exception as e:
        # H6: see query_knowledge_graph's identical comment above.
        logger.error(f"SQL execution error: {e}")
        return "SQL Query Error: the query could not be executed. See server logs for detail."

@mcp.tool()
@track_tool_call
def check_data_quality(
    table_name: Annotated[str, Field(description="Table name (e.g. 'deposit_account')")],
) -> str:
    """
    Fetch real-time OpenMetadata Data Quality test suite assertions, scorecards, and SLAs.
    """
    logger.info(f"Executing check_data_quality tool for table '{table_name}'")
    try:
        # Resolve table_name to its exact catalog FQN first, rather than
        # guessing which schema (financial vs ref) it lives in or
        # substring-matching every test case's entityFQN against it -- the
        # previous substring check ("party" in entityFQN) also matched
        # party_individual/party_organization/party_role_customer/
        # party_address/party_identification, none of which are the table
        # actually asked about. Exact match on the search hit's own `name`
        # field avoids that same trap at the resolution step too.
        search_url = f"{OPENMETADATA_URL}/search/query?q={urllib.parse.quote(table_name)}&index=table_search_index&size=10"
        search_req = urllib.request.Request(search_url, headers=HEADERS)
        with urllib.request.urlopen(search_req, timeout=10) as resp:
            hits = json.loads(resp.read().decode("utf-8")).get("hits", {}).get("hits", [])
        table_fqn = next(
            (h["_source"]["fullyQualifiedName"] for h in hits
             if h["_source"].get("name", "").lower() == table_name.lower()),
            None,
        )
        if table_fqn is None:
            return f"No table named '{table_name}' found in the catalog."

        # Test cases are grouped under a per-table test suite
        # (<table_fqn>.testSuite, the same convention
        # execute_openmetadata_data_quality_tests.py registers them under);
        # its numeric id -- not its FQN, verified live that a `testSuite=
        # <fqn>` filter is silently ignored rather than rejected -- is what
        # dataQuality/testCases actually filters by via `testSuiteId`. A
        # table with no registered test suite yet (404 here) has no
        # assertions to report, not an error.
        suite_url = f"{OPENMETADATA_URL}/dataQuality/testSuites/name/{urllib.parse.quote(table_fqn)}.testSuite"
        suite_req = urllib.request.Request(suite_url, headers=HEADERS)
        try:
            with urllib.request.urlopen(suite_req, timeout=10) as resp:
                suite_id = json.loads(resp.read().decode("utf-8"))["id"]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return f"No active data quality assertions for {table_name}."
            raise

        # testSuiteId returns every test case belonging to this exact table
        # -- both table-level (row count, ...) and column-level (not-null,
        # uniqueness, ...) -- unlike the entityLink filter, which only
        # matches the table-level test case's own exact entityLink string.
        tests_url = f"{OPENMETADATA_URL}/dataQuality/testCases?testSuiteId={suite_id}&limit=100&fields=testCaseResult"
        tests_req = urllib.request.Request(tests_url, headers=HEADERS)
        with urllib.request.urlopen(tests_req, timeout=10) as resp:
            test_cases = json.loads(resp.read().decode("utf-8")).get("data", [])
        results = []
        for tc in test_cases:
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

_hybrid_retriever = None


def _get_hybrid_retriever():
    """Lazily builds a single HybridRAGRetriever, reused across every
    hybrid_rag_search call for the life of this process, instead of
    constructing a fresh one (with its own fresh Postgres connection and
    Neo4j driver -- see HybridRAGRetriever's own connection-reuse comment)
    per invocation (Q6). Deferred to first call rather than built at import
    time so importing this module never triggers the embedding/reranker
    model load a tool that isn't hybrid_rag_search wouldn't need."""
    global _hybrid_retriever
    if _hybrid_retriever is None:
        from scripts.hybrid_rag_retriever import HybridRAGRetriever
        _hybrid_retriever = HybridRAGRetriever()
    return _hybrid_retriever


@mcp.tool()
@track_tool_call
def hybrid_rag_search(
    prompt: Annotated[str, Field(description="Natural language prompt")],
) -> str:
    """
    Execute full 4-tier Hybrid RAG context search (Vector Search + Cypher + Cube.js Metrics + SQL)
    for complex natural language questions.
    """
    logger.info(f"Executing hybrid_rag_search tool for prompt: '{prompt}'")
    try:
        retriever = _get_hybrid_retriever()
        payload = retriever.hybrid_retrieve(prompt)
        return json.dumps(payload, indent=2)
    except Exception as e:
        # Broad on purpose, matching every other tool's error-handling
        # convention here (search_data_catalog, check_data_quality, ...) --
        # this used to catch only RuntimeError (raised by
        # scripts._embedding_backend when the real embedding/cross-encoder
        # model can't load and ALLOW_DEGRADED_EMBEDDINGS isn't set), which
        # was Q6's "only tool with no try/except" finding in a different
        # guise: a downstream connection failure (e.g. no live Postgres/Neo4j
        # reachable) raises psycopg2/neo4j exceptions, not RuntimeError, and
        # those escaped straight to the transport instead of surfacing as a
        # clean tool error.
        logger.error(f"Hybrid RAG search error: {e}")
        return f"Hybrid RAG Search Error: {e}"

# -----------------------------------------------------------------------------
# MCP RESOURCES
# -----------------------------------------------------------------------------

@mcp.resource("financial://catalog/schema")
def get_catalog_schema_resource() -> str:
    """Provides full documentation of PostgreSQL schemas `ref` and `financial`.

    D8 (hardening plan): this previously hardcoded only 8 of the platform's
    20 real tables (7 financial tables shared with 3 contracts, plus
    `party_role_customer`) -- an agent asking this resource "what tables
    exist" got an answer that silently omitted 12 real tables, including
    every `deposit_*`/`loan_*` sub-entity and all 3 `ref.*` reference
    tables. Now lists every table in `schema.dbml` (itself kept
    non-drifting against the live DB by `scripts/generate_schema_dbml.py
    --check` / `tests/test_schema_dbml_drift.py` -- see D7), with the same
    one-line descriptions as that file's own `Note:` blocks so this doesn't
    become a second, independently-drifting summary of the same 20 tables.
    """
    return """
    PostgreSQL Database Schemas:

    financial.* (BIAN/FIBO domain tables, SCD Type 2 temporal headers):
    Party & Customer Domain:
    1. `financial.party`: Master Party entity supertype (BIAN Party Domain).
    2. `financial.party_individual`: Individual natural person party subtype (Name, DOB -- PII).
    3. `financial.party_organization`: Organization legal entity party subtype (Legal Name, Reg Number -- PII).
    4. `financial.party_role_customer`: Customer role context assigned to a party (KYC status, AML risk rating).
    5. `financial.party_address`: Physical and registered address details for parties.
    6. `financial.party_identification`: Official identification and tax documents for parties (Passport/National ID/Tax ID/LEI -- PII).

    Deposit & Liquidity Domain:
    7. `financial.deposit_account`: BIAN Current & Savings deposit account core contract entity.
    8. `financial.deposit_balance`: Deposit account real-time balance snapshot.
    9. `financial.deposit_transaction`: Deposit transaction accounting journal records.
    10. `financial.deposit_interest_term`: Deposit account interest terms and accrual rates.
    11. `financial.deposit_overdraft_facility`: Approved overdraft facility bounds for deposit accounts.

    Loan & Credit Risk Domain:
    12. `financial.loan_application`: Loan origination and credit application lifecycle.
    13. `financial.loan_agreement`: Core contractual loan agreement (FIBO Loan Agreement).
    14. `financial.loan_repayment_schedule`: Amortization repayment schedule installments.
    15. `financial.loan_disbursement`: Loan principal disbursement execution events.
    16. `financial.loan_collateral`: Pledged security assets securing loan contracts (Real Estate, Vehicle, Securities, Cash).

    17. `financial.entity_embeddings`: pgvector HNSW embedding store for catalog entities, FIBO ontology classes, and semantic cubes (hybrid RAG retrieval).

    ref.* (shared reference data, no SCD2 header -- read-only lookups):
    18. `ref.ref_country`: ISO 3166-1 country reference table (includes AML risk flag).
    19. `ref.ref_currency`: ISO 4217 currency reference table.
    20. `ref.ref_nace_industry`: NACE Rev. 2 industry classification reference table (includes risk level).
    """

@mcp.resource("financial://data-contracts/slas")
def get_data_contracts_slas_resource() -> str:
    """Provides formal Data Contract SLA specifications for enterprise data
    products, read live from contracts/*.yaml (D2: previously a third,
    independently hand-maintained copy of the same SLA figures already
    declared in those files -- see scripts/_contracts.py)."""
    return render_sla_summary()

def main():
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    port = int(os.getenv("MCP_PORT", "8001"))
    # Defaults to loopback-only, not 0.0.0.0 -- this server executes arbitrary
    # (guardrail-checked) SQL/Cypher; binding every interface should be an
    # explicit choice, not the out-of-the-box behavior. This default is what
    # actually applies when running this module's SSE mode directly on a
    # host (outside Docker) -- set MCP_HOST=0.0.0.0 there to deliberately
    # bind every interface.
    #
    # H4 (hardening plan): docker-compose.yml's `mcp_sidecar` service moved
    # off `network_mode: "host"` onto a bridge network, and now hardcodes
    # MCP_HOST=0.0.0.0 in its own `environment:` block (not read from
    # `.env`) -- required for Docker's own port-forwarding and for
    # Prometheus (a bridge peer scraping :8000) to reach this process at
    # all, since a container's own 127.0.0.1 is unreachable from outside
    # that same container under bridge networking, not just from the host.
    # `.env`'s own MCP_HOST is a genuinely different control now: it sets
    # the *host-side* interface docker-compose publishes mcp_sidecar's
    # ports to (mirroring OPENMETADATA_HOST's existing role for
    # openmetadata_server), not this process's own bind address inside
    # that container. This `os.getenv("MCP_HOST", "127.0.0.1")` call and
    # its safe default are otherwise unchanged.
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

        # Real Prometheus metrics, served from this process (the one actually
        # executing tool calls) rather than a separate simulator container --
        # see the TOOL_CALLS_TOTAL/TOOL_DURATION_MS comment above and
        # scripts/llmops_telemetry.py's module-level metrics. Unauthenticated,
        # matching Prometheus's own default scrape convention and this
        # endpoint's loopback-by-default binding.
        metrics_port = int(os.getenv("MCP_METRICS_PORT", "8000"))
        start_http_server(metrics_port, addr=host)
        logger.info(f"📊 Prometheus metrics available at http://{host}:{metrics_port}/metrics")

        logger.info(f"🚀 Launching Enterprise FastMCP Server (SSE HTTP Transport on http://{host}:{port})...")
        uvicorn.run(app, host=host, port=port, log_level="info")
    else:
        mcp.run()

if __name__ == "__main__":
    main()
