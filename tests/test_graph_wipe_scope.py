"""
The Neo4j reload in scripts/build_knowledge_graph.py used to be an
unconditional `MATCH (n) DETACH DELETE n`, which destroyed nodes it never
created and cannot recreate -- specifically the
(:PostgreSQLTable)-[:DERIVES_SEMANTICS_TO]->(:SemanticCube)-[:INSTANTIATES_GRAPH]->
(:KnowledgeEntityType) lineage sub-graph written afterwards by
scripts/sync_end_to_end_lineage.py. It only ever survived because
bootstrap_platform.sh happens to run the lineage sync after the graph build;
re-running the graph build on its own silently removed that layer.

The wipe is now scoped to `ABOX_LABELS`. That turns a correctness property
into a list someone has to remember to update, so these tests exist to make
forgetting it fail loudly:

  - a new loader label missing from ABOX_LABELS would leave stale nodes behind
    on every reload (silent, and exactly the failure the allowlist trades for)
  - a non-ABox label creeping into ABOX_LABELS would resurrect the original bug

Both are checked statically against the script's own source, so this runs in
CI with no Neo4j. The live half (that non-ABox nodes actually survive a real
rebuild) is asserted in the same style as tests/test_postgres_readonly_role.py:
skipped cleanly when no database is reachable.
"""

import os
import re

import pytest

from scripts.build_knowledge_graph import ABOX_LABELS

SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "build_knowledge_graph.py"
)

# Labels written by OTHER scripts into the same database. Neo4j Community
# permits only one user database (verified live: CREATE DATABASE returns
# Neo.ClientError.Statement.UnsupportedAdministrationCommand), so these
# necessarily share a graph with the ABox and must never be wiped by it.
FOREIGN_LABELS = {
    # scripts/sync_end_to_end_lineage.py
    "PostgreSQLTable",
    "SemanticCube",
    "KnowledgeEntityType",
    # scripts/load_ontology_tbox.py (the TBox layer)
    "OntologyClass",
    "OntologyProperty",
    "ExternalConcept",
}


def test_foreign_labels_matches_the_tbox_loaders_own_list():
    """Keeps FOREIGN_LABELS honest: the TBox loader owns the authoritative list
    of labels it writes, so drift there must surface here rather than silently
    leaving a new TBox label unprotected from the ABox wipe."""
    from scripts.load_ontology_tbox import TBOX_LABELS

    missing = set(TBOX_LABELS) - FOREIGN_LABELS
    assert not missing, (
        f"load_ontology_tbox.py writes {sorted(missing)}, which this test does not treat as "
        f"protected. Add them to FOREIGN_LABELS."
    )


def _labels_created_by_the_script() -> set:
    """Every label the loaders actually write, scraped from the script's own
    Cypher. Deliberately independent of ABOX_LABELS -- comparing the constant
    against itself would be vacuous."""
    with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
        source = f.read()
    # `MERGE (p:Party {...})` and `SET p:Individual, p.first_name = ...`
    merged = re.findall(r"MERGE \(\w+:([A-Za-z]+)", source)
    set_labels = re.findall(r"SET \w+:([A-Za-z]+)", source)
    return set(merged) | set(set_labels)


def test_scrape_finds_labels_at_all():
    """Guards the regex above: if it silently matched nothing, every other
    test in this file would pass vacuously."""
    found = _labels_created_by_the_script()
    assert len(found) >= 10, f"expected 10+ labels scraped from the loaders, got {sorted(found)}"


def test_every_created_label_is_wiped():
    """A loader label missing from ABOX_LABELS leaves stale nodes behind on
    every reload -- the silent-staleness failure the allowlist accepts in
    exchange for never deleting another layer's data."""
    missing = _labels_created_by_the_script() - set(ABOX_LABELS)
    assert not missing, (
        f"build_knowledge_graph.py creates {sorted(missing)} but ABOX_LABELS does not list "
        f"them -- they would survive the reload as stale nodes. Add them to ABOX_LABELS."
    )


def test_abox_labels_contains_nothing_it_does_not_create():
    """The inverse: ABOX_LABELS must not name a label this script never
    writes, or the wipe reaches into another layer's data."""
    extra = set(ABOX_LABELS) - _labels_created_by_the_script()
    assert not extra, (
        f"ABOX_LABELS lists {sorted(extra)}, which build_knowledge_graph.py never creates. "
        f"The wipe must not delete nodes this script cannot rebuild."
    )


def test_foreign_labels_are_never_wiped():
    """The whole point: lineage and TBox labels must stay out of the wipe."""
    overlap = set(ABOX_LABELS) & FOREIGN_LABELS
    assert not overlap, (
        f"ABOX_LABELS includes {sorted(overlap)}, which is written by another script. "
        f"Wiping it reintroduces the original whole-graph-delete bug."
    )


def test_wipe_is_not_a_whole_graph_delete():
    """Regression guard on the exact statement that caused the bug.

    Checks executable lines only. The comment above ABOX_LABELS quotes the old
    statement verbatim to explain why the allowlist exists -- that prose is
    worth keeping, so a naive substring check over the whole file would fail on
    its own documentation.
    """
    with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
        code = "\n".join(
            line for line in f.read().splitlines() if not line.lstrip().startswith("#")
        )
    assert "MATCH (n) DETACH DELETE n" not in code, (
        "build_knowledge_graph.py contains an unscoped whole-graph delete, which destroys "
        "the lineage and ontology layers it cannot rebuild."
    )


# ---------------------------------------------------------------------------
# Live check -- skipped cleanly when no Neo4j is reachable (CI has none).
# ---------------------------------------------------------------------------


def test_wipe_leaves_foreign_labels_intact():
    """Proves the property end to end against a real graph: deleting every
    ABox label must not remove a foreign-label node. Runs inside a rolled-back
    transaction so it never mutates the real graph."""
    from scripts._dotenv_boot import load_env

    load_env()
    if not os.getenv("NEO4J_PASSWORD"):
        pytest.skip("NEO4J_PASSWORD not set -- no live graph configured")

    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
            connection_timeout=3,
        )
        driver.verify_connectivity()
    except Exception as e:  # noqa: BLE001 -- any driver/connection failure means "no live graph"
        pytest.skip(f"No live Neo4j reachable: {e}")

    try:
        with driver.session() as session:
            tx = session.begin_transaction()
            try:
                tx.run("CREATE (:SemanticCube {name: '__wipe_scope_probe__'})")
                for label in ABOX_LABELS:
                    tx.run(f"MATCH (n:{label}) DETACH DELETE n")
                survived = tx.run(
                    "MATCH (c:SemanticCube {name: '__wipe_scope_probe__'}) RETURN count(c) AS c"
                ).single()["c"]
                assert survived == 1, "a foreign-label node was destroyed by the ABox wipe"
            finally:
                # Never commit -- the real graph is left exactly as found.
                tx.rollback()
    finally:
        driver.close()
