"""
Q3 in the hardening plan: Tiers 3 (Cube.js) and 4 (SQL) of hybrid_rag_retriever.py
used to always run the same fixed query regardless of the prompt. This checks
the static structure of the fix (every classify_intent() outcome has a
corresponding Tier 3/4 query, and the SQL is syntactically sane) without
needing live Postgres/Cube.js -- the live, real-data version of this check was
run manually and is documented in the hardening plan's Q3 entry.
"""

from scripts.hybrid_rag_retriever import TIER3_INTENT_QUERY_MAP, TIER4_INTENT_QUERY_MAP
from scripts.text_to_cypher_builder import (
    INTENT_AML_RISK,
    INTENT_COLLATERAL,
    INTENT_DEFAULT,
    INTENT_DEPOSIT,
)

ALL_INTENTS = {INTENT_COLLATERAL, INTENT_DEPOSIT, INTENT_AML_RISK, INTENT_DEFAULT}


def test_tier3_map_covers_every_intent():
    assert set(TIER3_INTENT_QUERY_MAP.keys()) == ALL_INTENTS


def test_tier4_map_covers_every_intent():
    assert set(TIER4_INTENT_QUERY_MAP.keys()) == ALL_INTENTS


def test_tier3_entries_are_well_formed():
    for intent, (cube_name, measures, dimensions) in TIER3_INTENT_QUERY_MAP.items():
        assert isinstance(cube_name, str) and cube_name
        assert isinstance(measures, list) and len(measures) >= 1
        assert dimensions is None or isinstance(dimensions, list)


def test_tier4_entries_are_read_only_select():
    for intent, sql in TIER4_INTENT_QUERY_MAP.items():
        assert sql.strip().upper().startswith("SELECT")
        assert ";" not in sql.strip().rstrip(";")  # no stacked statements


def test_tier4_intents_produce_distinct_sql():
    # Regression guard for Q3's core complaint: every intent must route to a
    # genuinely different query, not variations that happen to look distinct
    # but collapse to the same SQL.
    all_sql = list(TIER4_INTENT_QUERY_MAP.values())
    assert len(set(all_sql)) == len(all_sql)


def test_tier3_intents_produce_distinct_measures():
    all_measure_tuples = [tuple(m) for _c, m, _d in TIER3_INTENT_QUERY_MAP.values()]
    assert len(set(all_measure_tuples)) == len(all_measure_tuples)
