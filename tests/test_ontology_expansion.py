"""
Tests for scripts/_ontology_expansion.py -- TBox-driven query expansion.

The matching and expansion rules are pure functions of a concept list, so the
whole reasoning path is checked offline in CI against a small hand-built TBox
fixture rather than against whatever happens to be loaded in a live graph. The
live half (that a real prompt against the real ontology reaches real tables,
and that the composed SQL runs) skips cleanly when no database is reachable,
matching tests/test_ontology_tbox.py.

`test_select_tables_*` are the ones that matter most: `select_tables()` is the
security boundary of this feature -- table names arrive from Neo4j and must
never be able to shape SQL -- so its rejection behaviour is asserted directly
rather than inferred from the SQL builder's output.
"""

import os

import pytest

from scripts import _ontology_expansion as oe

# A miniature TBox in the exact shape TBOX_FETCH_CYPHER returns, including the
# Party -> {Individual, Organization} hierarchy that makes subclass expansion
# observable, and one concept with no grounding.
CONCEPTS = [
    {
        "concept": "fin:Party", "label": "Party Supertype", "definition": "",
        "uri": "http://example.org/fin#Party",
        "subclasses": ["fin:Individual", "fin:Organization"],
        "grounded_in": ["fibo-party:Party"],
        "source_table": "financial.party", "semantic_cube": "Cube_Party",
    },
    {
        "concept": "fin:Individual", "label": "Individual Person", "definition": "",
        "uri": "http://example.org/fin#Individual",
        "subclasses": [], "grounded_in": ["fibo-people:Person"],
        "source_table": "financial.party_individual", "semantic_cube": "Cube_PartyIndividual",
    },
    {
        "concept": "fin:Organization", "label": "Organization Legal Entity", "definition": "",
        "uri": "http://example.org/fin#Organization",
        "subclasses": [], "grounded_in": ["fibo-org:LegalEntity"],
        "source_table": "financial.party_organization", "semantic_cube": "Cube_PartyOrganization",
    },
    {
        "concept": "fin:DepositAccount", "label": "Deposit Account", "definition": "",
        "uri": "http://example.org/fin#DepositAccount",
        "subclasses": [], "grounded_in": ["fibo-account:DepositAccount"],
        "source_table": "financial.deposit_account", "semantic_cube": "Cube_DepositAccount",
    },
    {
        "concept": "fin:LoanAgreement", "label": "Loan Agreement", "definition": "",
        "uri": "http://example.org/fin#LoanAgreement",
        "subclasses": [], "grounded_in": ["fibo-loan:Loan"],
        "source_table": "financial.loan_agreement", "semantic_cube": "Cube_LoanAgreement",
    },
    {
        "concept": "fin:Ungrounded", "label": "Ungrounded Concept", "definition": "",
        "uri": "http://example.org/fin#Ungrounded",
        "subclasses": [], "grounded_in": [], "source_table": None, "semantic_cube": None,
    },
]

ALLOWED = {
    "party": True, "party_individual": True, "party_organization": True,
    "deposit_account": True, "loan_agreement": True,
    "ref_country": False,  # real table, no SCD2 header -- the has_active_flag=False case
}


# ---------------------------------------------------------------------------
# Token normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("word,expected", [
    ("accounts", "account"), ("parties", "party"), ("addresses", "address"),
    ("account", "account"), ("address", "address"),
    ("is", "is"),        # too short to strip -- must not become "i"
    ("business", "business"),  # -ss must not lose its tail
])
def test_singularize(word, expected):
    assert oe._singularize(word) == expected


def test_normalize_tokens_lowercases_and_splits():
    assert oe.normalize_tokens("Overdrawn Deposit-Accounts!") == {"overdrawn", "deposit", "account"}


def test_normalize_tokens_on_empty_input():
    assert oe.normalize_tokens("") == set()
    assert oe.normalize_tokens(None) == set()


# ---------------------------------------------------------------------------
# Concept term derivation
# ---------------------------------------------------------------------------

def test_local_name_from_uri_fragment():
    assert oe.local_name(CONCEPTS[3]) == "DepositAccount"


def test_local_name_falls_back_to_curie_without_uri():
    assert oe.local_name({"concept": "fin:Thing", "uri": None}) == "Thing"


def test_concept_terms_splits_camel_case():
    name_tokens, _ = oe.concept_terms(CONCEPTS[3])
    assert name_tokens == {"deposit", "account"}


def test_concept_terms_drops_modelling_stopwords_from_label():
    """'Party Supertype' must contribute 'party' but not 'supertype' -- the
    latter describes the model, not the business concept, and would match
    prompts that have nothing to do with parties."""
    _, label_tokens = oe.concept_terms(CONCEPTS[0])
    assert "party" in label_tokens
    assert "supertype" not in label_tokens


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def test_match_requires_every_token_not_any():
    """The rule that keeps expansion from degrading into 'all tables'. A bare
    'account' is evidence for DepositAccount only as much as for anything else
    with 'account' in its name, so it must match neither."""
    matched = {m["concept"] for m in oe.match_concepts("show me the account", CONCEPTS)}
    assert "fin:DepositAccount" not in matched


def test_match_on_full_name_phrase():
    matched = {m["concept"] for m in oe.match_concepts("overdrawn deposit accounts", CONCEPTS)}
    assert "fin:DepositAccount" in matched


def test_match_is_plural_insensitive():
    singular = {m["concept"] for m in oe.match_concepts("deposit account", CONCEPTS)}
    plural = {m["concept"] for m in oe.match_concepts("deposit accounts", CONCEPTS)}
    assert singular == plural == {"fin:DepositAccount"}


def test_match_records_reason():
    matched = oe.match_concepts("loan agreement", CONCEPTS)
    assert [m["match_reason"] for m in matched] == ["name"]


def test_match_on_unrelated_prompt_returns_nothing():
    assert oe.match_concepts("what is the weather tomorrow", CONCEPTS) == []


def test_match_on_empty_prompt_returns_nothing():
    assert oe.match_concepts("", CONCEPTS) == []


def test_matching_is_not_vacuous():
    """Anti-vacuity guard in the style of test_ontology_tbox.py: if the
    matching rules ever silently stop firing, every other assertion here still
    passes by matching nothing. This one fails."""
    matched = oe.match_concepts(
        "deposit account and loan agreement exposure for parties", CONCEPTS
    )
    assert len(matched) >= 3


# ---------------------------------------------------------------------------
# Subclass expansion
# ---------------------------------------------------------------------------

def test_expand_pulls_in_subclasses():
    """The payoff: 'parties' reaches Individual and Organization because the
    ontology asserts the hierarchy, not because anyone enumerated it here."""
    expanded = oe.expand_subclasses(oe.match_concepts("master parties", CONCEPTS), CONCEPTS)
    assert {e["concept"] for e in expanded} == {
        "fin:Party", "fin:Individual", "fin:Organization"
    }


def test_expanded_subclasses_are_labelled_with_their_parent():
    expanded = oe.expand_subclasses(oe.match_concepts("parties", CONCEPTS), CONCEPTS)
    reasons = {e["concept"]: e["match_reason"] for e in expanded}
    assert reasons["fin:Individual"] == "subclass_of:fin:Party"
    assert reasons["fin:Party"] == "name"


def test_expand_deduplicates_when_parent_and_child_both_match():
    matched = oe.match_concepts("parties and individuals", CONCEPTS)
    expanded = oe.expand_subclasses(matched, CONCEPTS)
    curies = [e["concept"] for e in expanded]
    assert len(curies) == len(set(curies))


def test_expand_skips_subclass_curies_with_no_node():
    """A dangling subclass reference is dropped, not synthesized -- a
    half-known concept in a retrieval payload is worse than an absent one."""
    dangling = [{
        "concept": "fin:Party", "label": "Party Supertype", "uri": "http://x#Party",
        "subclasses": ["fin:DoesNotExist"], "grounded_in": [],
        "source_table": "financial.party", "semantic_cube": None,
    }]
    expanded = oe.expand_subclasses(oe.match_concepts("party", dangling), dangling)
    assert [e["concept"] for e in expanded] == ["fin:Party"]


def test_grounded_tables_dedupes_and_drops_ungrounded():
    tables = oe.grounded_tables([
        {"source_table": "financial.party"},
        {"source_table": "financial.party"},
        {"source_table": None},
    ])
    assert tables == ["financial.party"]


# ---------------------------------------------------------------------------
# select_tables -- the security boundary
# ---------------------------------------------------------------------------

def test_select_tables_accepts_allowlisted():
    assert oe.select_tables(["financial.party"], ALLOWED) == ["financial.party"]


def test_select_tables_drops_unknown_table():
    """Graph content is not authoritative. A node naming a table that does not
    exist in information_schema contributes nothing."""
    assert oe.select_tables(["financial.not_a_real_table"], ALLOWED) == []


@pytest.mark.parametrize("hostile", [
    "financial.party; DROP TABLE financial.party",
    'financial.party" OR "1"="1',
    "financial.pg_shadow",
    "public.users",
    "financial.party--",
])
def test_select_tables_rejects_injection_shaped_names(hostile):
    """The allowlist is what makes this safe, so it is asserted directly: none
    of these appear in information_schema, so none survive -- regardless of
    what quoting the SQL builder would later apply."""
    assert oe.select_tables([hostile], ALLOWED) == []


def test_select_tables_deduplicates():
    assert oe.select_tables(["financial.party", "party"], ALLOWED) == ["financial.party"]


def test_select_tables_caps_at_max():
    many = [f"financial.t{i}" for i in range(oe.MAX_EXPANDED_TABLES + 5)]
    allowed = {f"t{i}": False for i in range(oe.MAX_EXPANDED_TABLES + 5)}
    assert len(oe.select_tables(many, allowed)) == oe.MAX_EXPANDED_TABLES


def test_select_tables_on_empty_input():
    assert oe.select_tables([], ALLOWED) == []


# ---------------------------------------------------------------------------
# expand() end to end (pure -- no SQL without a connection)
# ---------------------------------------------------------------------------

def test_expand_without_context_omits_sql():
    """The concept-reasoning-only mode the MCP tool uses: it reports tables to
    query next, it does not build or run SQL."""
    result = oe.expand("deposit accounts", CONCEPTS)
    assert "expansion_sql" not in result
    assert result["grounded_tables"] == ["financial.deposit_account"]


def test_expand_reports_grounding_and_cube():
    result = oe.expand("deposit accounts", CONCEPTS)
    entry = result["expanded_concepts"][0]
    assert entry["grounded_in"] == ["fibo-account:DepositAccount"]
    assert entry["semantic_cube"] == "Cube_DepositAccount"


def test_expand_on_no_match_is_empty_not_everything():
    """Failure mode worth pinning: an unmatched prompt must expand to nothing,
    never to the whole ontology."""
    result = oe.expand("weather forecast", CONCEPTS)
    assert result["matched_concepts"] == []
    assert result["grounded_tables"] == []


def test_expand_ungrounded_concept_yields_no_table():
    result = oe.expand("ungrounded concept", CONCEPTS)
    assert [m["concept"] for m in result["matched_concepts"]] == ["fin:Ungrounded"]
    assert result["grounded_tables"] == []


# ---------------------------------------------------------------------------
# Live checks -- skipped when no database is reachable.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def retriever():
    from scripts._dotenv_boot import load_env

    load_env()
    if not os.getenv("NEO4J_PASSWORD") or not os.getenv("MCP_PG_READONLY_PASSWORD"):
        pytest.skip("NEO4J_PASSWORD/MCP_PG_READONLY_PASSWORD not set -- no live stack")
    try:
        from scripts.hybrid_rag_retriever import HybridRAGRetriever
        r = HybridRAGRetriever()
        r.query_pg("SELECT 1;")
        r.query_neo4j("RETURN 1 AS ok")
    except Exception as e:  # noqa: BLE001 -- any failure means "no live stack"
        pytest.skip(f"No live stack reachable: {e}")
    yield r
    r.close()


def test_live_tbox_fetch_returns_grounded_concepts(retriever):
    concepts = oe.fetch_concepts(retriever.query_neo4j)
    if not concepts:
        pytest.skip("TBox not loaded yet -- run: python3 scripts/load_ontology_tbox.py")
    assert any(c["source_table"] for c in concepts), "no concept is bridged to a source table"


def test_live_allowlist_comes_from_information_schema(retriever):
    allowed = retriever._get_allowed_tables()
    assert "party" in allowed, "financial.party missing from the live allowlist"
    assert allowed["party"] is True, "party should carry the SCD2 md_is_active flag"


def test_live_expansion_reaches_real_tables(retriever):
    """The end-to-end payoff, against the real ontology: a prompt that Tiers
    2-4 classify as INTENT_DEFAULT still reaches the tables that answer it."""
    concepts = oe.fetch_concepts(retriever.query_neo4j)
    if not concepts:
        pytest.skip("TBox not loaded yet")
    result = retriever.ontology_expansion_search(
        "Which organizations have pending loan applications?"
    )
    assert "financial.party_organization" in result["grounded_tables"]
    assert "financial.loan_application" in result["grounded_tables"]


def test_live_expansion_sql_executes_and_counts_rows(retriever):
    """Proves the composed SQL is valid and correctly quoted -- the half of
    build_grounded_sql() that cannot be checked without libpq."""
    result = retriever.ontology_expansion_search("deposit accounts")
    if not result.get("grounded_row_counts"):
        pytest.skip("TBox bridges not loaded yet")
    row = result["grounded_row_counts"][0]
    assert set(row) == {"source_table", "row_count"}
    assert row["row_count"] > 0


def test_live_subclass_expansion_widens_the_table_set(retriever):
    """Party alone would reach one table; the SUBCLASS_OF walk must reach the
    subtype tables too."""
    result = retriever.ontology_expansion_search("master party entities")
    if not result["grounded_tables"]:
        pytest.skip("TBox bridges not loaded yet")
    assert "financial.party_individual" in result["grounded_tables"]
    assert "financial.party_organization" in result["grounded_tables"]


def test_live_hybrid_payload_carries_the_ontology_tier(retriever):
    payload = retriever.hybrid_retrieve("deposit account balances")
    assert "ontology_expansion_context" in payload
    assert "Ontology_Expansion_TBox" not in payload["_tier_errors"], payload["_tier_errors"]
