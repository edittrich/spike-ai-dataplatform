"""
Negative security tests against the live `mcp_readonly` Postgres role (see
supabase/migrations/20260807151500_create_mcp_readonly_role.sql). These
exercise the database-level layer of defense-in-depth that the C2 finding's
remediation actually relies on -- the keyword guardrail in
ai_safety_guardrails.py catches syntactically-obvious mutations, but reading
`pg_shadow` or calling `pg_read_file` are ordinary-looking SELECTs that only
the role's restricted grants (and Postgres's own superuser-only catalog
security) stop.

Skipped automatically when no live database is reachable (e.g. in CI, which
has no Postgres service) -- these are integration tests, not unit tests, and
deliberately don't fake a connection to stay honest about what they verify.
"""

import os

import psycopg2
import pytest

from scripts._dotenv_boot import load_env

load_env()

MCP_PG_READONLY_USER = os.getenv("MCP_PG_READONLY_USER", "mcp_readonly")
MCP_PG_READONLY_PASSWORD = os.getenv("MCP_PG_READONLY_PASSWORD", "")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "54322"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")


@pytest.fixture(scope="module")
def readonly_conn():
    if not MCP_PG_READONLY_PASSWORD:
        pytest.skip("MCP_PG_READONLY_PASSWORD not set -- no live database configured")
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST, port=POSTGRES_PORT, user=MCP_PG_READONLY_USER,
            password=MCP_PG_READONLY_PASSWORD, dbname=POSTGRES_DB, connect_timeout=3,
        )
    except psycopg2.OperationalError as e:
        pytest.skip(f"No live Postgres reachable at {POSTGRES_HOST}:{POSTGRES_PORT}: {e}")
    yield conn
    conn.close()


def test_readonly_role_cannot_read_pg_shadow(readonly_conn):
    with readonly_conn.cursor() as cur, pytest.raises(psycopg2.Error):
        cur.execute("SELECT * FROM pg_shadow")
    readonly_conn.rollback()


def test_readonly_role_cannot_read_server_files(readonly_conn):
    with readonly_conn.cursor() as cur, pytest.raises(psycopg2.Error):
        cur.execute("SELECT pg_read_file('/etc/passwd')")
    readonly_conn.rollback()


def test_readonly_role_cannot_update(readonly_conn):
    with readonly_conn.cursor() as cur, pytest.raises(psycopg2.Error):
        cur.execute("UPDATE financial.party SET status_code = 'CLOSED'")
    readonly_conn.rollback()


def test_readonly_role_cannot_copy_to_program(readonly_conn):
    with readonly_conn.cursor() as cur, pytest.raises(psycopg2.Error):
        cur.execute("COPY (SELECT 1) TO PROGRAM 'id'")
    readonly_conn.rollback()


def test_readonly_role_can_read_financial_data(readonly_conn):
    # Sanity check: the role must still be able to do its actual job.
    with readonly_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM financial.party")
        assert cur.fetchone()[0] > 0
    readonly_conn.rollback()
