#!/usr/bin/env python3
"""
===============================================================================
Configure the mcp_readonly Postgres Role's Login Password
===============================================================================
supabase/migrations/20260807151500_create_mcp_readonly_role.sql creates the
`mcp_readonly` role as NOLOGIN with no usable password -- migrations are checked
into git, so a real credential can never live there (see CLAUDE.md's Secrets
convention). This script sets that role's actual login password from the
MCP_PG_READONLY_PASSWORD env var (read from `.env`, never hardcoded), connecting
as the POSTGRES_USER superuser to do so.

Run this once after the migration has been applied, and again any time
MCP_PG_READONLY_PASSWORD changes in `.env`. Idempotent -- safe to re-run.
===============================================================================
"""

import logging
import os
import sys

import psycopg2
from psycopg2 import sql

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this module is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env  # noqa: E402

load_env()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ConfigureReadonlyRole")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "54322"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")

MCP_PG_READONLY_USER = os.getenv("MCP_PG_READONLY_USER", "mcp_readonly")
MCP_PG_READONLY_PASSWORD = os.getenv("MCP_PG_READONLY_PASSWORD", "")


def main() -> None:
    if not MCP_PG_READONLY_PASSWORD:
        logger.error(
            "MCP_PG_READONLY_PASSWORD is not set in .env -- refusing to leave the "
            "%s role with no usable password (it would stay NOLOGIN, which is safe "
            "but means the MCP server can't connect as it either).",
            MCP_PG_READONLY_USER,
        )
        sys.exit(1)
    if not POSTGRES_PASSWORD:
        logger.error("POSTGRES_PASSWORD is not set in .env -- cannot connect as superuser.")
        sys.exit(1)

    conn = psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT, user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, dbname=POSTGRES_DB, connect_timeout=10,
    )
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            # The role name is config-controlled (an env var, not user input), but
            # it's still an identifier -- %s parameterization only binds literal
            # values, not identifiers, so sql.Identifier is the correct quoting
            # mechanism here rather than an f-string.
            cur.execute(
                sql.SQL("ALTER ROLE {role} WITH LOGIN PASSWORD %s;").format(
                    role=sql.Identifier(MCP_PG_READONLY_USER)
                ),
                (MCP_PG_READONLY_PASSWORD,),
            )
        logger.info(
            "✅ %s can now authenticate with the password from MCP_PG_READONLY_PASSWORD.",
            MCP_PG_READONLY_USER,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
