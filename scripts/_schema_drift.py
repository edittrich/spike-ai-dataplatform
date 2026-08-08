#!/usr/bin/env python3
"""
===============================================================================
Contract <-> Schema Drift Check (static, CI-runnable)
===============================================================================
Parses the base migration SQL file directly -- not a live database
connection -- so this can run as a blocking CI gate without a Postgres
service. This is the check D2 in the hardening plan asked for: it would have
caught all three of the contract's phantom columns
(loan_agreement.agreement_reference, loan_collateral.valuation_amount,
party_organization.tax_identifier) and both contradictory `allowed_values`
sets (agreement_status, account_status) the day they were introduced, instead
of only being noticed by manual review.

Deliberately a lightweight regex parse of the CREATE TABLE / CHECK (... IN
(...)) blocks rather than a real SQL parser -- the migration file's
formatting is consistent enough (one column per line, one CHECK per column)
that this is reliable in practice, and it avoids adding a SQL-parsing
dependency for a single, narrowly-scoped check.
===============================================================================
"""

import os
import re

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is declared in requirements.txt
    yaml = None

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MIGRATION_PATH = os.path.join(
    REPO_ROOT, "supabase", "migrations", "20260722000000_create_financial_platform_schema.sql"
)
CONTRACTS_DIR = os.path.join(REPO_ROOT, "contracts")

_TABLE_BLOCK_RE = re.compile(
    r"CREATE TABLE (?:IF NOT EXISTS )?(?P<schema>\w+)\.(?P<table>\w+)\s*\((?P<body>.*?)\n\);",
    re.DOTALL,
)
_COLUMN_LINE_RE = re.compile(r"^\s*(?P<name>[a-z_][a-z0-9_]*)\s+[A-Z]")
_CHECK_IN_RE = re.compile(
    r"CHECK\s*\(\s*(?P<column>[a-z_][a-z0-9_]*)\s+IN\s*\((?P<values>[^)]*)\)\s*\)", re.IGNORECASE
)


def parse_migration_schema(migration_path=MIGRATION_PATH):
    """Returns {(schema, table): {"columns": {name,...}, "allowed_values": {col: {val,...}}}}."""
    with open(migration_path, "r", encoding="utf-8") as f:
        sql = f.read()

    tables = {}
    for m in _TABLE_BLOCK_RE.finditer(sql):
        schema, table, body = m.group("schema"), m.group("table"), m.group("body")
        columns = set()
        for line in body.split("\n"):
            col_match = _COLUMN_LINE_RE.match(line)
            if col_match:
                columns.add(col_match.group("name"))
        allowed_values = {}
        for check_match in _CHECK_IN_RE.finditer(body):
            col = check_match.group("column")
            values = re.findall(r"'([^']*)'", check_match.group("values"))
            allowed_values[col] = set(values)
        tables[(schema, table)] = {"columns": columns, "allowed_values": allowed_values}
    return tables


def find_drift(migration_path=MIGRATION_PATH, contracts_dir=CONTRACTS_DIR):
    """Returns a list of human-readable drift descriptions; empty if none."""
    if yaml is None:
        return ["PyYAML is not installed -- cannot parse contracts/*.yaml"]

    schema = parse_migration_schema(migration_path)
    problems = []

    for fname in sorted(os.listdir(contracts_dir)):
        if not fname.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(contracts_dir, fname)
        with open(path, "r", encoding="utf-8") as f:
            contract = yaml.safe_load(f) or {}

        for model_name, model in (contract.get("models") or {}).items():
            if "." not in model_name:
                problems.append(f"{fname}: model '{model_name}' is not schema-qualified (expected 'schema.table')")
                continue
            model_schema, model_table = model_name.split(".", 1)
            table_key = (model_schema, model_table)
            if table_key not in schema:
                problems.append(f"{fname}: model '{model_name}' has no matching CREATE TABLE in the migration")
                continue

            real_columns = schema[table_key]["columns"]
            real_allowed_values = schema[table_key]["allowed_values"]

            for col_name, col_def in (model.get("columns") or {}).items():
                if col_name not in real_columns:
                    problems.append(
                        f"{fname}: {model_name}.{col_name} does not exist in the live schema "
                        f"(phantom column -- see D2 in the hardening plan)"
                    )
                    continue
                declared_values = col_def.get("allowed_values")
                if declared_values and col_name in real_allowed_values:
                    real_values = real_allowed_values[col_name]
                    unwritable = set(declared_values) - real_values
                    if unwritable:
                        problems.append(
                            f"{fname}: {model_name}.{col_name} allowed_values {sorted(unwritable)} "
                            f"cannot ever be written -- the DB CHECK constraint only permits {sorted(real_values)}"
                        )
                    missing = real_values - set(declared_values)
                    if missing:
                        problems.append(
                            f"{fname}: {model_name}.{col_name} allowed_values is missing real value(s) "
                            f"{sorted(missing)} that the DB CHECK constraint permits"
                        )

    return problems


def main():
    problems = find_drift()
    if problems:
        print("❌ Contract <-> schema drift detected:")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(1)
    print("✅ All contracts/*.yaml columns and allowed_values match the live migration schema.")


if __name__ == "__main__":
    main()
