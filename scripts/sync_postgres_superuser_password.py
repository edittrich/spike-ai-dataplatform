#!/usr/bin/env python3
"""
===============================================================================
Sync the postgres Superuser's Password After a Supabase CLI Reset
===============================================================================
Real bug, found live while building the Dagster orchestration (Part 5 item 1
in the hardening plan): `supabase db reset` recreates the local Postgres
instance from the base image + migrations, and the Supabase CLI's local dev
stack has no `config.toml` option for a custom superuser password -- it
always resets `postgres`'s password back to the CLI's own fixed local-dev
default (`postgres`), silently overriding whatever custom value is in
`POSTGRES_PASSWORD` in `.env`. Every script and service in this platform that
connects as the `postgres` superuser using `.env`'s value (Cube.js,
`configure_readonly_role.py`, `build_knowledge_graph.py`,
`generate_vector_embeddings.py`, ...) would then fail authentication after a
fresh reset, until something explicitly re-synced the password -- previously
undocumented and unautomated, which is exactly the "Phase 0 -- make the
platform reproducible" gap this closes.

Run this once after every `npm run supabase:db:reset` (or
`supabase db reset`), before any other step that connects as the postgres
superuser. Idempotent and safe to run whether or not a sync is actually
needed:
  1. First tries connecting *as postgres* with the real POSTGRES_PASSWORD
     from `.env` -- if that already works (no reset happened since the last
     sync), this is a clean no-op.
  2. Falls back to connecting *as `supabase_admin`* with Supabase CLI's
     known local-dev default password ("postgres", overridable via
     SUPABASE_LOCAL_DB_DEFAULT_PASSWORD if a future CLI version ever changes
     it) -- if that connects, a reset just happened, so this ALTERs
     `postgres`'s password back to POSTGRES_PASSWORD. Deliberately not
     `postgres` itself for this step: despite the name, `postgres` is *not*
     Postgres's actual superuser in Supabase's role model
     (`rolsuper = false`; verified live via `SELECT rolname, rolsuper FROM
     pg_roles`) -- `supabase_admin` is the real one, and Postgres refuses
     "ALTER USER postgres ..." from a merely-elevated (non-super) role with
     `permission denied to alter role ... Only superusers can alter
     privileged roles`.
  3. If neither connects, fails loudly rather than silently proceeding with
     a broken connection every later step would also hit.
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
logger = logging.getLogger("SyncPostgresSuperuserPassword")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "54322"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")

# Not a "leaked secret" fallback of the kind CLAUDE.md's Secrets convention
# warns against -- this is a fixed, publicly-documented default the Supabase
# CLI itself assigns to every local dev instance, not a credential for
# anything this platform's own security model protects. Overridable in case
# a future Supabase CLI version changes it.
SUPABASE_LOCAL_DB_DEFAULT_PASSWORD = os.getenv("SUPABASE_LOCAL_DB_DEFAULT_PASSWORD", "postgres")


def _try_connect(user: str, password: str):
    try:
        return psycopg2.connect(
            host=POSTGRES_HOST, port=POSTGRES_PORT, user=user,
            password=password, dbname=POSTGRES_DB, connect_timeout=10,
        )
    except psycopg2.OperationalError:
        return None


def main() -> None:
    if not POSTGRES_PASSWORD:
        logger.error("POSTGRES_PASSWORD is not set in .env -- nothing to sync to.")
        sys.exit(1)

    conn = _try_connect(POSTGRES_USER, POSTGRES_PASSWORD)
    if conn is not None:
        logger.info("✅ postgres already authenticates with POSTGRES_PASSWORD from .env -- no reset detected, nothing to do.")
        conn.close()
        return

    # supabase_admin, not postgres itself -- see the module docstring for why.
    conn = _try_connect("supabase_admin", SUPABASE_LOCAL_DB_DEFAULT_PASSWORD)
    if conn is None:
        logger.error(
            "Could not authenticate as postgres with POSTGRES_PASSWORD from .env, or as "
            "supabase_admin with the Supabase CLI's local-dev default password. Is Postgres "
            "running (`npm run supabase:start`)? Check POSTGRES_HOST/PORT in .env."
        )
        sys.exit(1)

    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            # POSTGRES_USER is config-controlled (an env var, not user input), but
            # it's still an identifier -- %s parameterization only binds literal
            # values, not identifiers, so sql.Identifier is the correct quoting
            # mechanism here rather than an f-string.
            cur.execute(
                sql.SQL("ALTER USER {user} WITH PASSWORD %s;").format(user=sql.Identifier(POSTGRES_USER)),
                (POSTGRES_PASSWORD,),
            )
        logger.info(
            "✅ Detected a fresh Supabase reset (postgres was on the CLI's default password) -- "
            "synced it back to POSTGRES_PASSWORD from .env."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
