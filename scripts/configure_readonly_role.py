#!/usr/bin/env python3
"""
===============================================================================
Configure the Least-Privilege Postgres Roles' Login Passwords
===============================================================================
supabase/migrations/20260807151500_create_mcp_readonly_role.sql and
20260808150000_create_cube_readonly_role.sql create the `mcp_readonly` and
`cube_readonly` roles as NOLOGIN with no usable password -- migrations are
checked into git, so a real credential can never live there (see CLAUDE.md's
Secrets convention). This script sets both roles' actual login passwords from
their respective env vars (read from `.env`, never hardcoded), connecting as
the POSTGRES_USER superuser to do so.

H1 (hardening plan): cube_readonly is a deliberate sibling of mcp_readonly, not
a shared login -- Cube.js's own Postgres connections (docker-compose.yml's
CUBEJS_DB_USER/PASS) and the MCP server's/hybrid_rag_retriever's should be
distinguishable identities, not the same role reused because they happen to
need the same grants today. Both are configured by this one script (rather
than a near-duplicate second script) since the actual logic -- set a NOLOGIN
role's password from an env var, as the superuser -- is identical for both.

Run this once after the migrations have been applied, and again any time
either password env var changes in `.env`. Idempotent -- safe to re-run.
===============================================================================
"""

import logging
import os
import sys
from dataclasses import dataclass

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


@dataclass(frozen=True)
class ReadonlyRole:
    role_name: str
    password_env_var: str


# One entry per NOLOGIN read-only role created by a migration under
# supabase/migrations/ -- add a new role here (and its own migration) rather
# than introducing another near-identical configure script.
READONLY_ROLES = [
    ReadonlyRole(
        role_name=os.getenv("MCP_PG_READONLY_USER", "mcp_readonly"),
        password_env_var="MCP_PG_READONLY_PASSWORD",
    ),
    ReadonlyRole(
        role_name=os.getenv("CUBE_PG_READONLY_USER", "cube_readonly"),
        password_env_var="CUBE_PG_READONLY_PASSWORD",
    ),
]


def configure_role(conn, role: ReadonlyRole) -> bool:
    """Sets one role's login password from its env var. Returns False (and
    logs an error, without raising) if the env var is unset, so one missing
    password doesn't stop the other role from being configured."""
    password = os.getenv(role.password_env_var, "")
    if not password:
        logger.error(
            "%s is not set in .env -- refusing to leave the %s role with no usable "
            "password (it would stay NOLOGIN, which is safe but means its intended "
            "caller can't connect as it either).",
            role.password_env_var, role.role_name,
        )
        return False

    with conn.cursor() as cur:
        # The role name is config-controlled (an env var, not user input), but
        # it's still an identifier -- %s parameterization only binds literal
        # values, not identifiers, so sql.Identifier is the correct quoting
        # mechanism here rather than an f-string.
        cur.execute(
            sql.SQL("ALTER ROLE {role} WITH LOGIN PASSWORD %s;").format(
                role=sql.Identifier(role.role_name)
            ),
            (password,),
        )
    logger.info(
        "✅ %s can now authenticate with the password from %s.",
        role.role_name, role.password_env_var,
    )
    return True


def main() -> None:
    if not POSTGRES_PASSWORD:
        logger.error("POSTGRES_PASSWORD is not set in .env -- cannot connect as superuser.")
        sys.exit(1)

    conn = psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT, user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, dbname=POSTGRES_DB, connect_timeout=10,
    )
    try:
        conn.autocommit = True
        results = [configure_role(conn, role) for role in READONLY_ROLES]
    finally:
        conn.close()

    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
