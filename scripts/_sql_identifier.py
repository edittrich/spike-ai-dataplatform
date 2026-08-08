#!/usr/bin/env python3
"""
===============================================================================
SQL Identifier Validation (defense-in-depth for unavoidable interpolation)
===============================================================================
psycopg2 can parameterize *values* (`%s`) but not identifiers -- a schema,
table, or column name can never be a bind parameter. Scripts that build
`SELECT COUNT({col}) FROM {schema}.{table}` from names obtained externally
(the OpenMetadata catalog API, in this codebase) must validate those names
before interpolating them, per the C6 finding.

Two layers, both required:
  1. `validate_identifier` -- a syntactic check. Rejects anything that isn't
     a bare `[A-Za-z_][A-Za-z0-9_]*` token: no quotes, whitespace, semicolons,
     dots, or SQL keywords/operators can survive this regardless of source.
  2. `load_known_columns` / `is_known_column` -- a semantic allowlist check.
     Fetches the real (schema, table, column) triples straight from
     `information_schema.columns` and rejects anything not present there --
     so even a syntactically-valid identifier can't reference a column that
     doesn't actually exist in `financial`/`ref`.
===============================================================================
"""

import re

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_identifier(name: str, kind: str = "identifier") -> str:
    """Raises ValueError unless `name` is a bare SQL identifier token."""
    if not name or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL {kind} rejected: {name!r}")
    return name


def load_known_columns(query_pg, schemas=("financial", "ref")):
    """Returns {(schema, table): {column, ...}} from information_schema.columns
    for the given schemas, via the caller's own `query_pg(sql) -> str` helper
    (kept as a parameter rather than importing one, since each pipeline
    script's `query_pg` shells out to a slightly different docker container /
    connection -- this module has no opinion on how the query gets run).
    """
    schema_list = ", ".join(f"'{validate_identifier(s, 'schema')}'" for s in schemas)
    sql = (
        "SELECT table_schema, table_name, column_name FROM information_schema.columns "
        f"WHERE table_schema IN ({schema_list});"
    )
    known = {}
    for line in query_pg(sql).split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) != 3:
            continue
        schema, table, column = parts
        known.setdefault((schema, table), set()).add(column)
    return known


def is_known_column(known_columns, schema: str, table: str, column: str) -> bool:
    return column in known_columns.get((schema, table), set())


def is_known_table(known_columns, schema: str, table: str) -> bool:
    return (schema, table) in known_columns
