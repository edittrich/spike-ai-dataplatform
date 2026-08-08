"""
===============================================================================
Generic SCD Type 2 close-and-insert utility (D3 in the hardening plan)
===============================================================================
Q13 added a real *schema-level guarantee* that no two rows sharing a
business key can have overlapping validity ranges (`EXCLUDE USING gist` on
all 7 business-key tables -- see
supabase/migrations/20260807160000_schema_integrity_constraints_and_indexes.sql)
-- but that constraint only rejects a bad write; nothing in this codebase
ever *performed* a close-and-insert write. `scripts/generate_synthetic_data.py`
writes historical-looking rows directly into the seed file (some with
`md_is_active = FALSE` baked in from the start); it never executes an
UPDATE-then-INSERT the way a real SCD2 pipeline eventually will.

`scd2_update()` below is that operation, generic across any of the 7 real
business-key tables (SCD2_TABLES). This module deliberately does *not*
accept an arbitrary caller-supplied schema/table/column the way
`scripts/_sql_identifier.py`'s allowlist-against-`information_schema`
machinery was built for (C6's context: an OpenMetadata API response naming
a column) -- the identifiers used here are a small, fixed, reviewed
constant in this file, not externally influenceable input, so
`psycopg2.sql.Identifier`'s own quoting is sufficient defense; there is no
runtime identifier to validate against a live schema.

See `scripts/demo_scd2_update.py` for a live, runnable demonstration of
this function against the real database.
===============================================================================
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from psycopg2 import sql


@dataclass(frozen=True)
class Scd2TableSpec:
    schema: str
    table: str
    pk_column: str
    business_key_column: str


# The 7 tables Q13's migration added a business-key EXCLUDE USING gist
# constraint to. Keep this in sync with that migration if a table's
# business key ever changes -- there's no drift check for this one (unlike
# D2/D7's contract/schema.dbml checks) since it's a small, rarely-changing,
# hand-reviewed constant, not machine-generated content.
SCD2_TABLES: dict[str, Scd2TableSpec] = {
    "party": Scd2TableSpec("financial", "party", "party_id", "party_bk"),
    "party_role_customer": Scd2TableSpec(
        "financial", "party_role_customer", "party_role_customer_id", "customer_number"
    ),
    "deposit_account": Scd2TableSpec(
        "financial", "deposit_account", "deposit_account_id", "account_number"
    ),
    "deposit_transaction": Scd2TableSpec(
        "financial", "deposit_transaction", "deposit_transaction_id", "transaction_reference"
    ),
    "loan_application": Scd2TableSpec(
        "financial", "loan_application", "loan_application_id", "application_number"
    ),
    "loan_agreement": Scd2TableSpec(
        "financial", "loan_agreement", "loan_agreement_id", "agreement_number"
    ),
    "loan_disbursement": Scd2TableSpec(
        "financial", "loan_disbursement", "loan_disbursement_id", "disbursement_reference"
    ),
}

# Every SCD2 header column -- never copied forward from the old row into the
# new one; the new row always gets fresh values for these (see below).
_METADATA_COLUMNS = {
    "md_created_at_utc",
    "md_updated_at_utc",
    "md_valid_from_utc",
    "md_valid_to_utc",
    "md_is_active",
}


def scd2_update(
    conn: Any,
    table_key: str,
    business_key_value: str,
    changes: dict[str, Any],
) -> dict[str, Any]:
    """Applies a real SCD Type 2 close-and-insert update to the currently
    active row identified by `business_key_value` in `SCD2_TABLES[table_key]`.

    1. Locks the currently active row (`SELECT ... FOR UPDATE`) -- raises
       ValueError if none exists (business key not found, or found but
       already fully closed/historical).
    2. Closes it: `UPDATE ... SET md_valid_to_utc = <cutover>,
       md_is_active = FALSE WHERE <pk> = <old pk>`.
    3. Inserts a new row: every non-metadata, non-PK column copied from the
       closed row, with `changes` applied on top, plus fresh SCD2 headers.

    Both statements use the *same* Python-computed `cutover` timestamp for
    the old row's `md_valid_to_utc` and the new row's `md_valid_from_utc` --
    not two independent `NOW()` calls. Postgres range types are
    `[start, end)` (inclusive/exclusive), so identical boundaries make the
    two ranges exactly adjacent with no gap and no overlap; two independent
    `NOW()` calls could otherwise leave a race window in either direction,
    and Q13's own `EXCLUDE USING gist` constraint exists specifically to
    reject a genuine overlap between two versions of the same business key.

    Runs inside the caller's existing transaction -- does not call
    `commit()`/`rollback()` itself, so a caller can wrap this in a real
    transaction and roll it back for a side-effect-free verification run
    (see `scripts/demo_scd2_update.py`) or commit it for a real update.

    Returns {"old_pk", "new_pk", "old_row", "new_row"} -- the closed row's
    and the newly-inserted row's primary keys and full column dicts.
    """
    if table_key not in SCD2_TABLES:
        raise ValueError(f"Unknown SCD2 table key {table_key!r}; must be one of {sorted(SCD2_TABLES)}")
    spec = SCD2_TABLES[table_key]
    table_id = sql.Identifier(spec.schema, spec.table)
    pk_id = sql.Identifier(spec.pk_column)
    bk_id = sql.Identifier(spec.business_key_column)

    cutover = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        # 1. Lock the currently active row for this business key.
        cur.execute(
            sql.SQL("SELECT * FROM {} WHERE {} = %s AND md_is_active = TRUE FOR UPDATE").format(
                table_id, bk_id
            ),
            (business_key_value,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(
                f"No active row found in {spec.schema}.{spec.table} with "
                f"{spec.business_key_column} = {business_key_value!r}"
            )
        col_names = [d.name for d in cur.description]
        old_row = dict(zip(col_names, row))
        old_pk = old_row[spec.pk_column]

        # 2. Close the old row.
        cur.execute(
            sql.SQL(
                "UPDATE {} SET md_valid_to_utc = %s, md_is_active = FALSE, "
                "md_updated_at_utc = %s WHERE {} = %s"
            ).format(table_id, pk_id),
            (cutover, cutover, old_pk),
        )

        # 3. Insert the new version: old row's non-metadata, non-PK columns
        # with `changes` applied on top, plus fresh SCD2 headers.
        new_row = {
            k: v for k, v in old_row.items() if k != spec.pk_column and k not in _METADATA_COLUMNS
        }
        unknown_change_cols = set(changes) - set(new_row)
        if unknown_change_cols:
            raise ValueError(
                f"changes references column(s) not on {spec.schema}.{spec.table}: "
                f"{sorted(unknown_change_cols)}"
            )
        new_row.update(changes)
        new_row["md_created_at_utc"] = cutover
        new_row["md_updated_at_utc"] = cutover
        new_row["md_valid_from_utc"] = cutover
        # md_valid_to_utc / md_is_active are left to their column DEFAULTs
        # ('9999-12-31 23:59:59+00' / TRUE) by omission -- the same defaults
        # every other currently-active row in these tables relies on.

        insert_cols = list(new_row.keys())
        insert_vals = [new_row[c] for c in insert_cols]
        cur.execute(
            sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING {}").format(
                table_id,
                sql.SQL(", ").join(sql.Identifier(c) for c in insert_cols),
                sql.SQL(", ").join([sql.Placeholder()] * len(insert_cols)),
                pk_id,
            ),
            insert_vals,
        )
        new_pk = cur.fetchone()[0]

    return {"old_pk": old_pk, "new_pk": new_pk, "old_row": old_row, "new_row": new_row}
