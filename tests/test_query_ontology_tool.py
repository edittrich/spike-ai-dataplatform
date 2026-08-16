"""
Tests for the `query_ontology` MCP tool.

The validation paths are fully offline -- the tool rejects a bad operation or a
missing term *before* touching Neo4j, so those run in CI with no database. The
query paths skip cleanly when no graph is reachable, matching
tests/test_postgres_readonly_role.py.

Also guards a coupling that has no other test: every tool registered with
FastMCP needs a matching branch in AgenticToolRunner.dispatch_tool, or an LLM
that calls it gets "Error: Unknown tool" at runtime with nothing failing at
build time.
"""

import json
import os

import pytest

from mcp_server.financial_data_mcp_server import query_ontology


# ---------------------------------------------------------------------------
# Offline: validation happens before any database call.
# ---------------------------------------------------------------------------


def test_unknown_operation_is_rejected_with_valid_options():
    """The caller is a model; the error has to be actionable enough for it to
    retry correctly, not just say no."""
    result = query_ontology("frobnicate", "x")
    assert "Unknown operation" in result
    for op in ("list", "describe", "search"):
        assert op in result


def test_operation_is_case_and_whitespace_insensitive():
    """Models produce ' Describe' and 'DESCRIBE'. Failing those would be a
    parsing gotcha, not a real constraint."""
    assert "Unknown operation" not in query_ontology("  DESCRIBE  ", "Customer")


@pytest.mark.parametrize("op", ["describe", "search"])
def test_operations_requiring_a_term_reject_an_empty_one(op):
    assert f"Operation '{op}' requires a non-empty `term`." == query_ontology(op, "")
    assert f"Operation '{op}' requires a non-empty `term`." == query_ontology(op, "   ")


def test_list_does_not_require_a_term():
    """'list' takes no term; demanding one would make discovery impossible for
    a caller that doesn't yet know any concept names."""
    assert "requires a non-empty" not in query_ontology("list", "")


# ---------------------------------------------------------------------------
# Offline: the tool must stay wired into the agentic dispatch.
# ---------------------------------------------------------------------------


def test_every_registered_tool_has_an_agentic_dispatch_branch():
    import inspect

    from scripts.agentic_tool_runner import LLM_TOOLS, AgenticToolRunner

    source = inspect.getsource(AgenticToolRunner.dispatch_tool)
    names = [t["function"]["name"] for t in LLM_TOOLS]
    assert len(names) >= 7, f"expected 7+ registered tools, got {names}"
    missing = [n for n in names if f'"{n}"' not in source]
    assert not missing, (
        f"{missing} are exposed to the LLM but have no branch in dispatch_tool -- calling "
        f"one returns 'Error: Unknown tool' at runtime with nothing failing at build time."
    )


# ---------------------------------------------------------------------------
# Live: skipped when no Neo4j / no loaded TBox.
# ---------------------------------------------------------------------------


def _tbox_available() -> bool:
    from scripts._dotenv_boot import load_env

    load_env()
    if not os.getenv("NEO4J_PASSWORD"):
        return False
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
            connection_timeout=3,
        )
        with driver.session() as s:
            n = s.run("MATCH (c:OntologyClass) RETURN count(c) AS c").single()["c"]
        driver.close()
        return n > 0
    except Exception:  # noqa: BLE001 -- any failure means "not available"
        return False


requires_tbox = pytest.mark.skipif(
    not _tbox_available(),
    reason="no live Neo4j with a loaded TBox (run scripts/load_ontology_tbox.py)",
)


@requires_tbox
def test_describe_returns_the_full_cross_layer_picture():
    """The payoff: one call answers what a concept means, what it's grounded
    in, and where its data physically lives."""
    rows = json.loads(query_ontology("describe", "DepositAccount"))
    assert len(rows) == 1
    row = rows[0]
    assert row["concept"] == "fin:DepositAccount"
    assert row["grounded_in"] == ["fibo-account:DepositAccount"]
    assert row["source_table"] == "financial.deposit_account"
    assert row["semantic_cube"] == "Cube_DepositAccount"
    assert row["instances"] > 0


@requires_tbox
def test_describe_resolves_curie_local_name_and_label():
    """All three are things a model will plausibly pass."""
    for term in ("fin:Customer", "Customer", "Customer Role"):
        rows = json.loads(query_ontology("describe", term))
        assert rows and rows[0]["concept"] == "fin:Customer", f"failed to resolve {term!r}"


@requires_tbox
def test_describe_reports_inherited_ancestors_not_just_direct_parents():
    """Transitive subsumption by reachability -- the substitute for a reasoner."""
    row = json.loads(query_ontology("describe", "Customer"))[0]
    assert "fin:PartyRole" in row["ancestors"]


@requires_tbox
def test_search_finds_concepts_by_free_text():
    rows = json.loads(query_ontology("search", "loan"))
    concepts = {r["concept"] for r in rows}
    assert {"fin:LoanAgreement", "fin:LoanApplication", "fin:LoanCollateral"} <= concepts
    assert all(r["source_table"] for r in rows), "search must point at where the data lives"


@requires_tbox
def test_list_returns_every_concept():
    rows = json.loads(query_ontology("list", ""))
    assert len(rows) == 10
    assert {"concept", "label", "grounded_in", "source_table", "instances"} <= set(rows[0])


@requires_tbox
def test_unknown_concept_gets_a_recoverable_message_not_an_empty_list():
    """An empty JSON array would read as 'this concept exists but has no
    detail'. The caller needs to know it should search instead."""
    result = query_ontology("describe", "Sasquatch")
    assert "No concept named" in result
    assert "search" in result


@requires_tbox
def test_no_instance_data_leaks_through_the_ontology_tool():
    """The TBox is terminological by construction. Assert the tool cannot
    return a customer name or similar, whatever the term."""
    for term in ("Individual", "Customer", "Party"):
        payload = query_ontology("describe", term).lower()
        for leak in ("first_name", "last_name", "date_of_birth", "aml_risk_rating", "customer_number"):
            assert leak not in payload, f"{leak} surfaced for term {term!r}"
