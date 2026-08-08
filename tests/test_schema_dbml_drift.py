"""
Confirms schema.dbml (see D7 in the hardening plan) matches what
scripts/generate_schema_dbml.py would produce from the live database right
now -- i.e. that it was regenerated, not hand-edited, after the last
migration. Requires a live Postgres connection (to introspect the real
schema), so this is skipped when none is reachable, same as
tests/test_postgres_readonly_role.py.
"""

import os

import psycopg2
import pytest

from scripts._dotenv_boot import load_env
from scripts.generate_schema_dbml import OUTPUT_PATH, generate_dbml

load_env()

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "54322"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")


def test_schema_dbml_matches_live_schema():
    if not POSTGRES_PASSWORD:
        pytest.skip("POSTGRES_PASSWORD not set -- no live database configured")
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST, port=POSTGRES_PORT, user=POSTGRES_USER,
            password=POSTGRES_PASSWORD, dbname=POSTGRES_DB, connect_timeout=3,
        )
        conn.close()
    except psycopg2.OperationalError as e:
        pytest.skip(f"No live Postgres reachable at {POSTGRES_HOST}:{POSTGRES_PORT}: {e}")

    generated = generate_dbml()
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        on_disk = f.read()
    assert on_disk == generated, (
        "schema.dbml is out of date -- run `python3 scripts/generate_schema_dbml.py` and commit the result."
    )
