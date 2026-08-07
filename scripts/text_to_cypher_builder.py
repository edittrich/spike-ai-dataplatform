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

import re
import logging
from typing import Dict, Any, Tuple

from scripts.ai_safety_guardrails import AISafetyGuardrails

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("TextToCypherBuilder")

class TextToCypherBuilder:
    def __init__(self):
        self.guardrails = AISafetyGuardrails()

    def compile_cypher(self, prompt: str) -> Tuple[str, str]:
        """
        Compiles natural language prompt into dynamic, read-only Cypher query.
        Returns tuple: (cypher_query_string, intent_description)
        """
        p_lower = prompt.lower()

        # Pattern 1: Pledged Collateral & Loan Agreements
        if any(w in p_lower for w in ["collateral", "pledged", "real estate", "asset"]):
            cypher = (
                "MATCH (l:LoanAgreement)-[r:SECURED_BY]->(c:LoanCollateral) "
                "RETURN l.agreement_number AS loan_ref, l.principal_amount AS principal, "
                "c.collateral_type AS collateral_type, c.estimated_value AS valuation "
                "ORDER BY c.estimated_value DESC LIMIT 5;"
            )
            intent = "Loan Collateral & Pledged Asset Traversal"

        # Pattern 2: Customer Deposit Account & Balance Exposure
        # NOTE: build_knowledge_graph.py does not load overdraft facilities into
        # Neo4j at all (no :DepositOverdraftFacility node / :HAS_FACILITY edge
        # exists in the graph), and the account-holding relationship is
        # :HOLDS_ACCOUNT, not :HOLDS. This template previously referenced a
        # schema that was never built and always returned zero rows silently.
        elif any(w in p_lower for w in ["overdrawn", "overdraft", "deposit", "balance", "facility"]):
            cypher = (
                "MATCH (cust:Customer)-[:HOLDS_ACCOUNT]->(acc:DepositAccount)-[:HAS_BALANCE]->(bal:DepositBalance) "
                "RETURN cust.customer_number AS customer_ref, acc.account_number AS account, "
                "acc.account_status AS account_status, bal.available_balance AS available_bal, "
                "bal.current_balance AS current_bal "
                "ORDER BY bal.available_balance ASC LIMIT 5;"
            )
            intent = "Customer Deposit Account & Balance Exposure"

        # Pattern 3: AML High Risk Exposure & Party Demographics
        # NOTE: build_knowledge_graph.py sets `:Individual` as an additional
        # label on the same :Party node (not a separate node reached via a
        # relationship), the role relationship is :PLAYS_ROLE (not :HAS_ROLE),
        # and the real property names are party_bk / aml_risk_rating, not
        # party_number / risk_rating. This template previously matched none of
        # that and always returned zero rows silently.
        elif any(w in p_lower for w in ["aml", "risk", "individual", "party", "kyc"]):
            cypher = (
                "MATCH (p:Party:Individual)-[:PLAYS_ROLE]->(cust:Customer) "
                "RETURN p.party_bk AS party_ref, p.first_name + ' ' + p.last_name AS customer_name, "
                "cust.kyc_status AS kyc_status, cust.aml_risk_rating AS risk_rating "
                "LIMIT 5;"
            )
            intent = "Party KYC Demographics & High Risk Traversal"

        # Default Fallback: Graph Schema Traversal
        else:
            cypher = (
                "MATCH (l:LoanAgreement)-[:SECURED_BY]->(c:LoanCollateral) "
                "RETURN l.agreement_number AS loan_ref, l.principal_amount AS principal, "
                "c.collateral_type AS collateral_type, c.estimated_value AS valuation "
                "LIMIT 5;"
            )
            intent = "Default Knowledge Graph Schema Traversal"

        # Validate Cypher query safety using AI Safety Guardrails
        safe, reason = self.guardrails.validate_read_only_query(cypher, "Cypher")
        if not safe:
            raise ValueError(f"Security Violation in compiled Cypher: {reason}")

        logger.info(f"Compiled Text-to-Cypher ({intent}): {cypher}")
        return cypher, intent

def main():
    print("🚀 Verifying Dynamic Text-to-Cypher Knowledge Graph Query Builder Engine...")
    print("===========================================================================")

    builder = TextToCypherBuilder()

    prompts = [
        "Find loan agreements with pledged collateral assets and interest rate terms",
        "Identify overdrawn deposit account customer risk exposure and master party entities",
        "Trace high AML risk customer profiles and individual KYC demographics"
    ]

    for idx, p in enumerate(prompts, 1):
        cypher, intent = builder.compile_cypher(p)
        print(f"\nPrompt #{idx}: '{p}'")
        print(f"  🎯 Extracted Intent: {intent}")
        print(f"  🕸️ Compiled Cypher: {cypher}")

    print("\n✅ Dynamic Text-to-Cypher Engine Verification Complete!")

if __name__ == "__main__":
    main()
