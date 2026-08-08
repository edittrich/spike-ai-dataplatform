#!/usr/bin/env python3
"""
===============================================================================
Dynamic Text-to-Cypher Knowledge Graph Query Builder Engine
===============================================================================
Translates natural language financial queries into optimized, read-only Neo4j
Cypher graph traversal queries:
1. Extract Entity Labels (:Individual, :Customer, :DepositAccount, :LoanAgreement, :LoanCollateral)
2. Extract Filter Predicates (AML risk, facility status, loan amount thresholds)
3. Compile & Validate Cypher Queries via AI Safety Guardrails
===============================================================================
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import logging
from typing import Tuple

from scripts.ai_safety_guardrails import AISafetyGuardrails

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("TextToCypherBuilder")

# Q3 (hardening plan): shared keyword-classification categories. Previously
# each of hybrid_rag_retriever.py's tiers routed on the prompt independently
# (Tier 2 here; Tiers 3/4 not at all -- see hybrid_rag_retriever.py's own
# comment on INTENT_TO_*_QUERY). Extracted classify_intent() below so all
# three dynamic tiers agree on what the user is asking about instead of each
# guessing separately -- previously possible (if Tier 3/4 had grown their own
# copies) for Tier 2 to route to "AML risk" while Tier 3 returned deposit
# balance data for the same prompt.
INTENT_COLLATERAL = "collateral"
INTENT_DEPOSIT = "deposit"
INTENT_AML_RISK = "aml_risk"
INTENT_DEFAULT = "default"


class TextToCypherBuilder:
    def __init__(self):
        self.guardrails = AISafetyGuardrails()

    def classify_intent(self, prompt: str) -> str:
        """Keyword-based intent classification, shared by every dynamic RAG
        tier (see module docstring). Returns one of the INTENT_* constants
        above."""
        p_lower = prompt.lower()
        if any(w in p_lower for w in ["collateral", "pledged", "real estate", "asset"]):
            return INTENT_COLLATERAL
        if any(w in p_lower for w in ["overdrawn", "overdraft", "deposit", "balance", "facility"]):
            return INTENT_DEPOSIT
        if any(w in p_lower for w in ["aml", "risk", "individual", "party", "kyc"]):
            return INTENT_AML_RISK
        return INTENT_DEFAULT

    def compile_cypher(self, prompt: str) -> Tuple[str, str]:
        """
        Compiles natural language prompt into dynamic, read-only Cypher query.
        Returns tuple: (cypher_query_string, intent_description)
        """
        intent = self.classify_intent(prompt)

        # Pattern 1: Pledged Collateral & Loan Agreements
        if intent == INTENT_COLLATERAL:
            cypher = (
                "MATCH (l:LoanAgreement)-[r:SECURED_BY]->(c:LoanCollateral) "
                "RETURN l.agreement_number AS loan_ref, l.principal_amount AS principal, "
                "c.collateral_type AS collateral_type, c.estimated_value AS valuation "
                "ORDER BY c.estimated_value DESC LIMIT 5;"
            )
            intent_desc = "Loan Collateral & Pledged Asset Traversal"

        # Pattern 2: Customer Deposit Account & Balance Exposure
        # NOTE: build_knowledge_graph.py does not load overdraft facilities into
        # Neo4j at all (no :DepositOverdraftFacility node / :HAS_FACILITY edge
        # exists in the graph), and the account-holding relationship is
        # :HOLDS_ACCOUNT, not :HOLDS. This template previously referenced a
        # schema that was never built and always returned zero rows silently.
        elif intent == INTENT_DEPOSIT:
            cypher = (
                "MATCH (cust:Customer)-[:HOLDS_ACCOUNT]->(acc:DepositAccount)-[:HAS_BALANCE]->(bal:DepositBalance) "
                "RETURN cust.customer_number AS customer_ref, acc.account_number AS account, "
                "acc.account_status AS account_status, bal.available_balance AS available_bal, "
                "bal.current_balance AS current_bal "
                "ORDER BY bal.available_balance ASC LIMIT 5;"
            )
            intent_desc = "Customer Deposit Account & Balance Exposure"

        # Pattern 3: AML High Risk Exposure & Party Demographics
        # NOTE: build_knowledge_graph.py sets `:Individual` as an additional
        # label on the same :Party node (not a separate node reached via a
        # relationship), the role relationship is :PLAYS_ROLE (not :HAS_ROLE),
        # and the real property names are party_bk / aml_risk_rating, not
        # party_number / risk_rating. This template previously matched none of
        # that and always returned zero rows silently.
        elif intent == INTENT_AML_RISK:
            cypher = (
                "MATCH (p:Party:Individual)-[:PLAYS_ROLE]->(cust:Customer) "
                "RETURN p.party_bk AS party_ref, p.first_name + ' ' + p.last_name AS customer_name, "
                "cust.kyc_status AS kyc_status, cust.aml_risk_rating AS risk_rating "
                "LIMIT 5;"
            )
            intent_desc = "Party KYC Demographics & High Risk Traversal"

        # Default Fallback: Party Overview by Type. Q3 (hardening plan): this
        # used to be a byte-for-byte copy of Pattern 1's collateral query --
        # an unrecognized prompt silently returned collateral results with a
        # different intent *label* but identical content, giving the illusion
        # of routing. Now a genuinely distinct, generally-useful default
        # (verified live: `p.type` -- not `p.party_type`, a property that
        # doesn't exist on this node -- returns real INDIVIDUAL/ORGANIZATION
        # counts), and one that Tier 3/4's own INTENT_DEFAULT queries in
        # hybrid_rag_retriever.py agree with (same underlying question: "give
        # me a basic overview").
        else:
            cypher = (
                "MATCH (p:Party) RETURN p.type AS party_type, count(p) AS party_count "
                "ORDER BY party_count DESC;"
            )
            intent_desc = "Default Party Overview by Type"

        # Validate Cypher query safety using AI Safety Guardrails
        safe, reason = self.guardrails.validate_read_only_query(cypher, "Cypher")
        if not safe:
            raise ValueError(f"Security Violation in compiled Cypher: {reason}")

        logger.info(f"Compiled Text-to-Cypher ({intent_desc}): {cypher}")
        return cypher, intent_desc

def main():
    print("🚀 Verifying Dynamic Text-to-Cypher Knowledge Graph Query Builder Engine...")
    print("===========================================================================")

    builder = TextToCypherBuilder()

    prompts = [
        "Find loan agreements with pledged collateral assets and interest rate terms",
        "Identify overdrawn deposit account customer risk exposure and master party entities",
        "Trace high AML risk customer profiles and individual KYC demographics",
        # Q3 regression check: no keyword from any of the 3 patterns above --
        # must hit the genuinely distinct default, not silently reuse
        # Pattern 1's collateral query under a different label.
        "What time is the market open today",
    ]

    collateral_cypher = None
    for idx, p in enumerate(prompts, 1):
        cypher, intent = builder.compile_cypher(p)
        print(f"\nPrompt #{idx}: '{p}'")
        print(f"  🎯 Extracted Intent: {intent}")
        print(f"  🕸️ Compiled Cypher: {cypher}")
        if idx == 1:
            collateral_cypher = cypher
        if idx == 4:
            assert cypher != collateral_cypher, (
                "Q3 regression: the default branch is returning the same Cypher as "
                "the collateral pattern again."
            )
            assert intent == "Default Party Overview by Type"

    print("\n✅ Dynamic Text-to-Cypher Engine Verification Complete!")

if __name__ == "__main__":
    main()
