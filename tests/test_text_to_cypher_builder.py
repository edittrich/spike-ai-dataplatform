"""
Q3 in the hardening plan: "Two of four RAG tiers ignore the question" (Tiers
3/4 in hybrid_rag_retriever.py were hardcoded regardless of the prompt) and
"[TextToCypherBuilder's] default branch returns the same collateral query as
branch 1 -- an unrecognised prompt silently yields collateral results."

No live services needed: TextToCypherBuilder only does keyword
classification + string templating at construction and call time.
"""

import pytest

from scripts.text_to_cypher_builder import (
    INTENT_AML_RISK,
    INTENT_COLLATERAL,
    INTENT_DEFAULT,
    INTENT_DEPOSIT,
    TextToCypherBuilder,
)


@pytest.fixture
def builder():
    return TextToCypherBuilder()


@pytest.mark.parametrize(
    "prompt,expected_intent",
    [
        ("Find loan agreements with pledged collateral assets", INTENT_COLLATERAL),
        ("real estate valuation for a loan", INTENT_COLLATERAL),
        ("overdrawn deposit account balance", INTENT_DEPOSIT),
        ("customer overdraft facility exposure", INTENT_DEPOSIT),
        ("high AML risk customer KYC status", INTENT_AML_RISK),
        ("individual party demographics", INTENT_AML_RISK),
        ("what time is the market open today", INTENT_DEFAULT),
        ("hello", INTENT_DEFAULT),
    ],
)
def test_classify_intent(builder, prompt, expected_intent):
    assert builder.classify_intent(prompt) == expected_intent


def test_default_branch_is_not_a_copy_of_collateral_branch(builder):
    # The exact regression Q3 named: an unrecognized prompt must not
    # silently return the same Cypher as the collateral pattern.
    collateral_cypher, _ = builder.compile_cypher("pledged collateral assets")
    default_cypher, default_intent = builder.compile_cypher("what time is it")
    assert default_cypher != collateral_cypher
    assert "collateral" not in default_cypher.lower()
    assert default_intent == "Default Party Overview by Type"


def test_compile_cypher_intent_matches_classify_intent(builder):
    # compile_cypher's internal classification must never disagree with the
    # standalone classify_intent() other tiers key off of (see
    # hybrid_rag_retriever.py's shared_intent) -- if it did, Tier 2 would
    # route to one topic while Tiers 3/4 routed to another for the same prompt.
    for prompt in ("pledged collateral", "overdrawn deposit", "AML risk", "unrelated question"):
        intent = builder.classify_intent(prompt)
        _cypher, intent_desc = builder.compile_cypher(prompt)
        if intent == INTENT_COLLATERAL:
            assert "Collateral" in intent_desc
        elif intent == INTENT_DEPOSIT:
            assert "Deposit" in intent_desc
        elif intent == INTENT_AML_RISK:
            assert "Risk" in intent_desc
        else:
            assert intent_desc == "Default Party Overview by Type"


def test_every_compiled_cypher_passes_the_guardrail(builder):
    # compile_cypher raises if its own output fails validate_read_only_query
    # -- exercise all 4 branches to confirm none of them ever would.
    for prompt in ("collateral", "deposit", "aml risk", "anything else"):
        cypher, _intent = builder.compile_cypher(prompt)
        assert cypher.strip().upper().startswith("MATCH")
