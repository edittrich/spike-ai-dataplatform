#!/usr/bin/env python3
"""
===============================================================================
JSON-Safe Row Normalization
===============================================================================
query_pg/query_neo4j used to return plain pipe/comma-delimited strings
(everything already stringified via `str(v)`), so nothing downstream ever
needed to worry about JSON-serializing a raw database value. Now that they
return list[dict] of the actual Python objects psycopg2/neo4j hand back
(Q2), a few common column/property types are not JSON-serializable by
default and would raise `TypeError` from json.dumps() calls this codebase
already makes without a `default=` handler -- most importantly
ai_safety_guardrails.py's sanitize_context_payload(), which every hybrid RAG
response passes through. Normalize once, right where rows leave the
database layer, rather than requiring every caller to remember to.
===============================================================================
"""

import datetime
import decimal
import uuid


def json_safe_value(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return value


def json_safe_row(row: dict) -> dict:
    return {k: json_safe_value(v) for k, v in row.items()}
