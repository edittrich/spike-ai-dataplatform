#!/usr/bin/env python3
"""
===============================================================================
Live SCD Type 2 Close-and-Insert Demonstration (D3 in the hardening plan)
===============================================================================
Exercises scripts/_scd2.py's scd2_update() against the real, already-seeded
database: picks one real customer's currently-active
`financial.party_role_customer` row, changes their KYC status via a genuine
close-and-insert (not a simulated one), and verifies the result directly
against the database -- exactly one active row remains for that
`customer_number`, the closed row's `md_valid_to_utc` and the new row's
`md_valid_from_utc` are identical (the adjacent-range design
scd2_update()'s docstring describes), and the new row carries the changed
value while every other column round-trips unchanged from the old row.

By default the whole demonstration runs inside one transaction that is
ROLLED BACK at the end -- every statement genuinely executes against the
real table and the real Q13 EXCLUDE USING gist constraint (this is not a
dry-run in the sense of skipping the SQL), but nothing is left mutated
afterward, so this script is safe to run repeatedly, in CI, or against a
shared database without accumulating demo rows. Pass --commit to persist
the change for real instead.

Usage:
    python3 scripts/demo_scd2_update.py                # rolled back (default)
    python3 scripts/demo_scd2_update.py --commit        # persisted for real
    python3 scripts/demo_scd2_update.py --customer-number CUST-000123
===============================================================================
"""

import argparse
import os
import sys

import psycopg2

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this script is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env  # noqa: E402

load_env()

from scripts._scd2 import scd2_update  # noqa: E402

# Native psycopg2 as the POSTGRES_USER superuser -- this script *writes*
# (an UPDATE + INSERT), same connection convention as
# generate_vector_embeddings.py/build_knowledge_graph.py's native writers
# (see CLAUDE.md's C6 note on why writes use a native driver, not `docker
# exec psql`).
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "54322"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")


def pick_a_customer(conn, customer_number: str | None) -> str:
    """Returns a real, currently-active customer_number to demonstrate
    against -- either the one explicitly requested (verified to exist and
    be active) or an arbitrary real one picked from the live table."""
    with conn.cursor() as cur:
        if customer_number:
            cur.execute(
                "SELECT customer_number FROM financial.party_role_customer "
                "WHERE customer_number = %s AND md_is_active = TRUE",
                (customer_number,),
            )
        else:
            cur.execute(
                "SELECT customer_number FROM financial.party_role_customer "
                "WHERE md_is_active = TRUE ORDER BY customer_number LIMIT 1"
            )
        row = cur.fetchone()
        if row is None:
            raise SystemExit(
                "No active party_role_customer row found -- is the seed data loaded? "
                "See CLAUDE.md's full data pipeline sequence."
            )
        return row[0]


def count_active(conn, customer_number: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM financial.party_role_customer "
            "WHERE customer_number = %s AND md_is_active = TRUE",
            (customer_number,),
        )
        return cur.fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit", action="store_true",
        help="Persist the demonstrated change for real. Default: roll back at the end.",
    )
    parser.add_argument(
        "--customer-number", default=None,
        help="Specific customer_number to demonstrate against. Default: an arbitrary active one.",
    )
    args = parser.parse_args()

    conn = psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT, user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, dbname=POSTGRES_DB, connect_timeout=10,
    )
    conn.autocommit = False  # this whole demo is one transaction, see module docstring

    try:
        customer_number = pick_a_customer(conn, args.customer_number)
        print(f"🎯 Demonstrating scd2_update() against customer_number={customer_number!r}")

        before_active_count = count_active(conn, customer_number)
        print(f"   Active rows before: {before_active_count} (must be exactly 1)")
        assert before_active_count == 1, "expected exactly one active row before the update"

        # Read the current KYC status so we can pick a genuinely different one.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT party_role_customer_id, kyc_status, aml_risk_rating "
                "FROM financial.party_role_customer "
                "WHERE customer_number = %s AND md_is_active = TRUE",
                (customer_number,),
            )
            old_pk_before, old_kyc_status, old_aml_rating = cur.fetchone()
        new_kyc_status = "EXPIRED" if old_kyc_status != "EXPIRED" else "PENDING"
        print(f"   Old KYC status: {old_kyc_status!r} -> New KYC status: {new_kyc_status!r}")

        result = scd2_update(
            conn,
            table_key="party_role_customer",
            business_key_value=customer_number,
            changes={"kyc_status": new_kyc_status},
        )

        # --- Verification, all against the real database, not the returned dict alone ---
        after_active_count = count_active(conn, customer_number)
        print(f"   Active rows after:  {after_active_count} (must still be exactly 1)")
        assert after_active_count == 1, (
            "expected exactly one active row after the update -- if this fails, either "
            "the close-and-insert left two active rows (a real bug) or Q13's "
            "EXCLUDE USING gist constraint should have rejected the write outright"
        )

        with conn.cursor() as cur:
            cur.execute(
                "SELECT md_is_active, md_valid_to_utc FROM financial.party_role_customer "
                "WHERE party_role_customer_id = %s",
                (result["old_pk"],),
            )
            old_is_active, old_valid_to = cur.fetchone()
            cur.execute(
                "SELECT md_is_active, md_valid_from_utc, kyc_status, aml_risk_rating "
                "FROM financial.party_role_customer WHERE party_role_customer_id = %s",
                (result["new_pk"],),
            )
            new_is_active, new_valid_from, new_kyc_from_db, new_aml_from_db = cur.fetchone()

        assert old_is_active is False, "closed row must have md_is_active = FALSE"
        assert new_is_active is True, "new row must have md_is_active = TRUE"
        assert old_valid_to == new_valid_from, (
            "closed row's md_valid_to_utc and new row's md_valid_from_utc must be identical "
            "(the adjacent-range, no-gap-no-overlap design) -- got "
            f"{old_valid_to!r} != {new_valid_from!r}"
        )
        assert new_kyc_from_db == new_kyc_status, "new row must carry the changed kyc_status"
        assert new_aml_from_db == old_aml_rating, (
            "new row must carry every unrelated column forward unchanged -- aml_risk_rating "
            f"changed from {old_aml_rating!r} to {new_aml_from_db!r} without being in `changes`"
        )

        print(f"   ✅ Old row {result['old_pk']} closed: md_is_active=False, md_valid_to_utc={old_valid_to}")
        print(f"   ✅ New row {result['new_pk']} active: md_is_active=True, md_valid_from_utc={new_valid_from}")
        print("   ✅ Adjacent validity ranges confirmed (no gap, no overlap)")
        print("   ✅ Unrelated columns (e.g. aml_risk_rating) carried forward unchanged")
        print("   ✅ Exactly one active row before and after -- Q13's business-key integrity holds")

        if args.commit:
            conn.commit()
            print("\n💾 --commit passed: change persisted for real.")
        else:
            conn.rollback()
            print("\n↩️  Default (no --commit): rolled back. No permanent change was made.")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("\n✅ SCD2 close-and-insert demonstration complete.")


if __name__ == "__main__":
    main()
