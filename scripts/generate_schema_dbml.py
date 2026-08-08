#!/usr/bin/env python3
"""
===============================================================================
schema.dbml Generator -- Introspects the Live Database
===============================================================================
Regenerates `schema.dbml` from the live PostgreSQL schema (information_schema
+ pg_catalog) instead of hand-maintaining it, which is how it drifted in the
first place (D7 in the hardening plan): `financial.entity_embeddings` was
missing entirely, 71 SCD2/timestamp columns were typed `timestamp` where the
live schema uses `TIMESTAMPTZ`, there was no schema qualification, and no
CHECK/exclusion constraints or indexes survived at all -- every one of those
facts is now read straight from the database rather than copied by hand.

Usage:
    python3 scripts/generate_schema_dbml.py [--check]

    --check   Don't write the file; exit 1 if the freshly-generated DBML
              differs from what's on disk. Intended for a CI drift check
              (see the pytest suite) -- run this after every migration to
              confirm schema.dbml was regenerated, not hand-edited.
===============================================================================
"""

import argparse
import os
import re
import sys

import psycopg2

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env  # noqa: E402

load_env()

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "54322"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")

SCHEMAS = ["ref", "financial"]
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "schema.dbml")

# information_schema.columns.data_type -> DBML type token. Anything not
# listed here (e.g. USER-DEFINED for pgvector's `vector`) is handled
# specially below rather than through this table.
TYPE_MAP = {
    "character varying": "varchar",
    "character": "char",
    "text": "text",
    "uuid": "uuid",
    "boolean": "boolean",
    "integer": "integer",
    "bigint": "bigint",
    "smallint": "smallint",
    "numeric": "numeric",
    "date": "date",
    "timestamp with time zone": "timestamptz",
    "timestamp without time zone": "timestamp",
    "jsonb": "jsonb",
    "json": "json",
}


def connect():
    return psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT, user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, dbname=POSTGRES_DB, connect_timeout=10,
    )


def dbml_type(col):
    data_type, udt_name, char_len, num_prec, num_scale = col
    if data_type == "USER-DEFINED" and udt_name == "vector":
        return "vector(384)"  # pgvector dimension is fixed platform-wide; see financial.entity_embeddings
    base = TYPE_MAP.get(data_type, data_type)
    if data_type in ("character varying", "character") and char_len:
        return f"{base}({char_len})"
    if data_type == "numeric" and num_prec is not None:
        return f"{base}({num_prec},{num_scale or 0})"
    return base


def fetch_tables(cur):
    cur.execute(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_schema = ANY(%s) AND table_type = 'BASE TABLE' "
        "ORDER BY table_schema, table_name",
        (SCHEMAS,),
    )
    return cur.fetchall()


def fetch_columns(cur, schema, table):
    cur.execute(
        """
        SELECT column_name, data_type, udt_name, character_maximum_length,
               numeric_precision, numeric_scale, is_nullable, column_default,
               col_description(format('%%I.%%I', table_schema, table_name)::regclass::oid, ordinal_position)
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    return cur.fetchall()


def fetch_table_comment(cur, schema, table):
    cur.execute("SELECT obj_description(%s::regclass::oid)", (f'"{schema}"."{table}"',))
    row = cur.fetchone()
    return row[0] if row else None


def fetch_constraints(cur, schema, table):
    """Returns dict: pk_col, fk={col: (ref_schema, ref_table, ref_col)},
    unique_cols=set(), other_notes=[def strings for CHECK/EXCLUDE]."""
    cur.execute(
        """
        SELECT contype, pg_get_constraintdef(c.oid)
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = %s AND t.relname = %s
        """,
        (schema, table),
    )
    pk_col = None
    fk = {}
    unique_cols = set()
    other_notes = []
    for contype, condef in cur.fetchall():
        if contype == "p":
            m = re.match(r"PRIMARY KEY \((\w+)\)", condef)
            if m:
                pk_col = m.group(1)
        elif contype == "f":
            m = re.match(r"FOREIGN KEY \((\w+)\) REFERENCES ([\w.]+)\((\w+)\)", condef)
            if m:
                col, ref_table_raw, ref_col = m.groups()
                if "." in ref_table_raw:
                    ref_schema, ref_table = ref_table_raw.split(".", 1)
                else:
                    ref_schema, ref_table = schema, ref_table_raw
                fk[col] = (ref_schema, ref_table, ref_col)
        elif contype == "u":
            m = re.match(r"UNIQUE \((\w+)\)", condef)
            if m:
                unique_cols.add(m.group(1))
            else:
                other_notes.append(condef)
        elif contype in ("c", "x"):
            other_notes.append(condef)
    return pk_col, fk, unique_cols, other_notes


def fetch_indexes(cur, schema, table):
    """Non-constraint indexes (constraint-backed indexes for PK/UNIQUE are
    already implied by the column flags, so they're excluded here to avoid
    duplicating them in the DBML Indexes {} block)."""
    cur.execute(
        """
        SELECT i.relname AS index_name, a.attname AS column_name, ix.indisunique,
               pg_get_expr(ix.indpred, ix.indrelid) AS partial_predicate
        FROM pg_index ix
        JOIN pg_class t ON t.oid = ix.indrelid
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
        WHERE n.nspname = %s AND t.relname = %s AND ix.indisprimary = false
          AND i.relname NOT IN (
              SELECT conname FROM pg_constraint c2
              JOIN pg_class t2 ON t2.oid = c2.conrelid
              JOIN pg_namespace n2 ON n2.oid = t2.relnamespace
              WHERE n2.nspname = %s AND t2.relname = %s AND c2.contype IN ('u', 'x')
          )
        ORDER BY i.relname, a.attnum
        """,
        (schema, table, schema, table),
    )
    indexes = {}
    for index_name, column_name, is_unique, predicate in cur.fetchall():
        entry = indexes.setdefault(index_name, {"columns": [], "unique": is_unique, "predicate": predicate})
        entry["columns"].append(column_name)
    return indexes


def dbml_escape(text):
    return (text or "").replace("\\", "\\\\").replace("'", "\\'")


def generate_dbml():
    conn = connect()
    try:
        cur = conn.cursor()
        tables = fetch_tables(cur)

        lines = [
            "// ============================================================================",
            "// DBML Specification: AI-Enabled Financial Data Platform PoC",
            "// Domain Standards: BIAN / FIBO Aligned Architecture",
            "// Temporal Pattern: Inmon 3NF with SCD Type 2 Metadata Headers",
            "//",
            "// GENERATED FILE -- do not hand-edit. Regenerate with:",
            "//   python3 scripts/generate_schema_dbml.py",
            "// after every migration, so this file can never drift from the live schema",
            "// the way the hand-maintained version did (missing entity_embeddings, 71",
            "// timestamp/TIMESTAMPTZ mismatches, no schema qualification -- see D7 in",
            "// the hardening plan).",
            "// ============================================================================",
            "",
            "Project AI_Financial_Data_Platform {",
            "  database_type: 'PostgreSQL'",
            "  Note: 'Production-grade BIAN/FIBO aligned financial data platform schema featuring Party, Deposit, and Loan domains with SCD Type 2 temporal metadata. Table names strictly prefixed by Data Product name. Schema-qualified (ref.*/financial.*).'",
            "}",
            "",
        ]

        current_schema = None
        for schema, table in tables:
            if schema != current_schema:
                current_schema = schema
                lines.append("// " + "-" * 76)
                lines.append(f"// {schema.upper()} SCHEMA")
                lines.append("// " + "-" * 76)
                lines.append("")

            columns = fetch_columns(cur, schema, table)
            pk_col, fk, unique_cols, other_notes = fetch_constraints(cur, schema, table)
            indexes = fetch_indexes(cur, schema, table)
            table_comment = fetch_table_comment(cur, schema, table)

            lines.append(f"Table {schema}.{table} {{")
            for (col_name, data_type, udt_name, char_len, num_prec, num_scale,
                 is_nullable, col_default, col_comment) in columns:
                attrs = []
                if col_name == pk_col:
                    attrs.append("pk")
                if col_name in unique_cols:
                    attrs.append("unique")
                if is_nullable == "NO" and col_name != pk_col:
                    attrs.append("not null")
                if col_default:
                    default_clean = re.sub(r"::\w[\w\s]*$", "", col_default)
                    if "nextval(" in default_clean:
                        pass  # sequence defaults aren't used in this schema; skip if ever present
                    elif re.match(r"^[A-Za-z_]+\(\)$", default_clean):
                        attrs.append(f"default: `{default_clean}`")
                    else:
                        attrs.append(f"default: {default_clean}")
                if col_name in fk:
                    ref_schema, ref_table, ref_col = fk[col_name]
                    attrs.append(f"ref: > {ref_schema}.{ref_table}.{ref_col}")
                if col_comment:
                    attrs.append(f"note: '{dbml_escape(col_comment)}'")

                type_str = dbml_type((data_type, udt_name, char_len, num_prec, num_scale))
                attr_str = f" [{', '.join(attrs)}]" if attrs else ""
                lines.append(f"  {col_name} {type_str}{attr_str}")

            if indexes:
                lines.append("")
                lines.append("  Indexes {")
                for idx_name, info in indexes.items():
                    cols = info["columns"][0] if len(info["columns"]) == 1 else f"({', '.join(info['columns'])})"
                    idx_attrs = [f"name: '{idx_name}'"]
                    if info["unique"]:
                        idx_attrs.append("unique")
                    if info["predicate"]:
                        idx_attrs.append(f"note: 'WHERE {dbml_escape(info['predicate'])}'")
                    lines.append(f"    {cols} [{', '.join(idx_attrs)}]")
                lines.append("  }")

            note_parts = []
            if table_comment:
                note_parts.append(table_comment)
            if other_notes:
                note_parts.append("Constraints: " + "; ".join(other_notes))
            if note_parts:
                lines.append("")
                lines.append(f"  Note: '{dbml_escape(' -- '.join(note_parts))}'")

            lines.append("}")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify schema.dbml is up to date; don't write it.")
    args = parser.parse_args()

    generated = generate_dbml()

    if args.check:
        existing = ""
        if os.path.exists(OUTPUT_PATH):
            with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
                existing = f.read()
        if existing != generated:
            print("❌ schema.dbml is out of date. Run `python3 scripts/generate_schema_dbml.py` and commit the result.")
            sys.exit(1)
        print("✅ schema.dbml matches the live schema.")
        return

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(generated)
    print(f"✅ Wrote {OUTPUT_PATH} from the live schema ({POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}).")


if __name__ == "__main__":
    main()
