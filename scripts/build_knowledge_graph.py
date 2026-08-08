#!/usr/bin/env python3
"""
===============================================================================
Knowledge Graph Construction Pipeline (PostgreSQL -> Neo4j)
===============================================================================
Extracts BIAN/FIBO aligned relational entities from PostgreSQL (Port 54322)
and instantiates a Knowledge Graph in Neo4j (Port 7474/7687).
===============================================================================
"""

import argparse
import json
import os
import subprocess
import sys

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this script is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env  # noqa: E402

load_env()

# _neo4j_conn reads NEO4J_URI/USER/PASSWORD at import time, so it must be
# imported *after* load_env() has populated the environment from .env --
# importing it earlier silently captures empty credentials.
from scripts._neo4j_conn import get_driver  # noqa: E402

# Connection Configs. Postgres is read-only here (SELECT ... FOR json_agg),
# which is why it still goes through `docker exec psql` -- see CLAUDE.md's
# note that this is an accepted convention for standalone, host-run pipeline
# scripts, as distinct from the MCP sidecar (which has no docker.sock at all)
# and from write paths (which must not use hand-escaped string interpolation;
# see the Cypher-writing functions below, and generate_vector_embeddings.py).
PG_CONTAINER = "supabase_db_ai-dataplatform"

def run_psql_json(sql_query):
    """Executes SQL against PostgreSQL container and returns parsed JSON array."""
    wrapped_sql = f"SELECT json_agg(t) FROM ({sql_query}) t;"
    cmd = [
        "docker", "exec", PG_CONTAINER,
        "psql", "-U", "postgres", "-d", "postgres", "-t", "-A", "-c", wrapped_sql
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"PostgreSQL Query Error: {res.stderr}")
        return []
    output = res.stdout.strip()
    if not output or output == "[null]":
        return []
    return json.loads(output)

def execute_cypher_batch(driver, statements_and_params):
    """Executes a list of (cypher_statement, parameters_dict) tuples against
    Neo4j via the native bolt driver -- parameters are bound server-side
    ($placeholders), never string-interpolated, closing the injection surface
    the old HTTP+f-string version had (see the C6 finding)."""
    if not statements_and_params:
        return
    try:
        with driver.session() as session:
            for statement, params in statements_and_params:
                result = session.run(statement, params or {})
                result.consume()
    except Exception as e:
        print(f"Cypher Error: {e}")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip the interactive confirmation before wiping the existing Neo4j graph.",
    )
    args = parser.parse_args()

    print("🚀 Starting Knowledge Graph Sync (PostgreSQL -> Neo4j)...")

    driver = get_driver()

    # 1. Clear existing database for clean reload -- this is a full, unconditional
    # wipe (MATCH (n) DETACH DELETE n), so it requires either an interactive "yes"
    # or an explicit --yes/-y flag (for non-interactive automation, e.g.
    # bootstrap_platform.sh, which passes --yes deliberately).
    print("🧹 Cleaning existing Neo4j graph...")
    if not args.yes:
        confirmed = os.getenv("CONFIRM_GRAPH_WIPE", "") == "1"
        if not confirmed and sys.stdin.isatty():
            answer = input(
                "⚠️  This will DELETE ALL nodes and relationships in the Neo4j graph "
                "at the configured NEO4J_URI. Type 'yes' to continue: "
            )
            confirmed = answer.strip().lower() == "yes"
        if not confirmed:
            print(
                "❌ Aborting: graph wipe was not confirmed. Re-run with --yes, or set "
                "CONFIRM_GRAPH_WIPE=1, to skip the interactive prompt."
            )
            driver.close()
            sys.exit(1)
    execute_cypher_batch(driver, [("MATCH (n) DETACH DELETE n", {})])

    # 2. Setup Uniqueness Constraints & Indexes
    print("⚡ Setting up Constraints & Indexes...")
    constraints = [
        ("CREATE CONSTRAINT IF NOT EXISTS FOR (p:Party) REQUIRE p.party_id IS UNIQUE", {}),
        ("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Customer) REQUIRE c.party_role_customer_id IS UNIQUE", {}),
        ("CREATE CONSTRAINT IF NOT EXISTS FOR (a:DepositAccount) REQUIRE a.deposit_account_id IS UNIQUE", {}),
        ("CREATE CONSTRAINT IF NOT EXISTS FOR (l:LoanAgreement) REQUIRE l.loan_agreement_id IS UNIQUE", {}),
        ("CREATE CONSTRAINT IF NOT EXISTS FOR (rc:RefCountry) REQUIRE rc.code IS UNIQUE", {}),
        ("CREATE CONSTRAINT IF NOT EXISTS FOR (rcur:RefCurrency) REQUIRE rcur.code IS UNIQUE", {}),
        ("CREATE CONSTRAINT IF NOT EXISTS FOR (rind:RefIndustry) REQUIRE rind.code IS UNIQUE", {}),
    ]
    execute_cypher_batch(driver, constraints)

    # 3. Load Reference Data (Currencies, Countries, Industries)
    # Every value below now travels as a Cypher $parameter -- bound server-side
    # by the driver, never string-interpolated into the query text -- instead
    # of the old per-field `str.replace("'", "\\'")` escaping, which silently
    # left several fields (gender, party_type, registration_number, every
    # numeric, ...) completely unescaped. See the C6 finding.
    print("🌐 Ingesting Reference Ontologies...")
    currencies = run_psql_json("SELECT currency_code, currency_name, symbol FROM ref.ref_currency")
    cypher_cur = [
        (
            "MERGE (c:RefCurrency {code: $code}) SET c.name = $name, c.symbol = $symbol",
            {"code": r["currency_code"], "name": r["currency_name"], "symbol": r.get("symbol") or ""},
        )
        for r in currencies
    ]
    execute_cypher_batch(driver, cypher_cur)

    countries = run_psql_json("SELECT country_code, country_name, is_high_risk_aml FROM ref.ref_country")
    cypher_cnt = [
        (
            "MERGE (c:RefCountry {code: $code}) SET c.name = $name, c.is_high_risk_aml = $is_high_risk_aml",
            {"code": r["country_code"], "name": r["country_name"], "is_high_risk_aml": bool(r["is_high_risk_aml"])},
        )
        for r in countries
    ]
    execute_cypher_batch(driver, cypher_cnt)

    industries = run_psql_json("SELECT nace_code, nace_title, risk_level FROM ref.ref_nace_industry")
    cypher_ind = [
        (
            "MERGE (i:RefIndustry {code: $code}) SET i.title = $title, i.risk_level = $risk_level",
            {"code": r["nace_code"], "title": r["nace_title"], "risk_level": r["risk_level"]},
        )
        for r in industries
    ]
    execute_cypher_batch(driver, cypher_ind)

    # 4. Load Core Parties & Roles
    print("👤 Ingesting Core Parties & Customer Roles...")
    parties = run_psql_json("SELECT party_id, party_bk, party_type, status_code FROM financial.party WHERE md_is_active = true")
    cypher_parties = [
        (
            "MERGE (p:Party {party_id: $party_id}) SET p.party_bk = $party_bk, p.type = $party_type, p.status = $status_code",
            {"party_id": r["party_id"], "party_bk": r["party_bk"], "party_type": r["party_type"], "status_code": r["status_code"]},
        )
        for r in parties
    ]
    execute_cypher_batch(driver, cypher_parties)

    individuals = run_psql_json("SELECT party_id, first_name, last_name, gender, citizenship_country_code FROM financial.party_individual WHERE md_is_active = true")
    cypher_indiv = [
        (
            "MATCH (p:Party {party_id: $party_id}) "
            "SET p:Individual, p.first_name = $first_name, p.last_name = $last_name, p.gender = $gender "
            "WITH p MATCH (c:RefCountry {code: $citizenship_country_code}) MERGE (p)-[:CITIZEN_OF]->(c)",
            {
                "party_id": r["party_id"], "first_name": r["first_name"], "last_name": r["last_name"],
                "gender": r["gender"], "citizenship_country_code": r["citizenship_country_code"],
            },
        )
        for r in individuals
    ]
    execute_cypher_batch(driver, cypher_indiv)

    orgs = run_psql_json("SELECT party_id, legal_name, registration_number, nace_code FROM financial.party_organization WHERE md_is_active = true")
    cypher_orgs = [
        (
            "MATCH (p:Party {party_id: $party_id}) "
            "SET p:Organization, p.legal_name = $legal_name, p.registration_number = $registration_number "
            "WITH p MATCH (i:RefIndustry {code: $nace_code}) MERGE (p)-[:OPERATES_IN_INDUSTRY]->(i)",
            {
                "party_id": r["party_id"], "legal_name": r["legal_name"],
                "registration_number": r["registration_number"], "nace_code": r["nace_code"],
            },
        )
        for r in orgs
    ]
    execute_cypher_batch(driver, cypher_orgs)

    customers = run_psql_json("SELECT party_role_customer_id, party_id, customer_number, customer_segment, kyc_status, aml_risk_rating FROM financial.party_role_customer WHERE md_is_active = true")
    cypher_cust = [
        (
            "MATCH (p:Party {party_id: $party_id}) "
            "MERGE (c:Customer {party_role_customer_id: $party_role_customer_id}) "
            "SET c.customer_number = $customer_number, c.segment = $customer_segment, "
            "c.kyc_status = $kyc_status, c.aml_risk_rating = $aml_risk_rating "
            "MERGE (p)-[:PLAYS_ROLE]->(c)",
            {
                "party_id": r["party_id"], "party_role_customer_id": r["party_role_customer_id"],
                "customer_number": r["customer_number"], "customer_segment": r["customer_segment"],
                "kyc_status": r["kyc_status"], "aml_risk_rating": r["aml_risk_rating"],
            },
        )
        for r in customers
    ]
    execute_cypher_batch(driver, cypher_cust)

    # 5. Load Deposit Domain
    print("💳 Ingesting Deposit Accounts & Balances...")
    accounts = run_psql_json("SELECT deposit_account_id, customer_id, account_number, account_type, account_status, currency_code FROM financial.deposit_account WHERE md_is_active = true")
    cypher_acc = [
        (
            "MATCH (c:Customer {party_role_customer_id: $customer_id}) "
            "MERGE (a:DepositAccount {deposit_account_id: $deposit_account_id}) "
            "SET a.account_number = $account_number, a.account_type = $account_type, "
            "a.account_status = $account_status, a.currency_code = $currency_code "
            "MERGE (c)-[:HOLDS_ACCOUNT]->(a) "
            "WITH a MATCH (cur:RefCurrency {code: $currency_code}) MERGE (a)-[:DENOMINATED_IN]->(cur)",
            {
                "customer_id": r["customer_id"], "deposit_account_id": r["deposit_account_id"],
                "account_number": r["account_number"], "account_type": r["account_type"],
                "account_status": r["account_status"], "currency_code": r["currency_code"],
            },
        )
        for r in accounts
    ]
    execute_cypher_batch(driver, cypher_acc)

    balances = run_psql_json("SELECT deposit_balance_id, deposit_account_id, available_balance, current_balance, ledger_balance, accrued_interest FROM financial.deposit_balance WHERE md_is_active = true")
    cypher_bal = [
        (
            "MATCH (a:DepositAccount {deposit_account_id: $deposit_account_id}) "
            "MERGE (b:DepositBalance {deposit_balance_id: $deposit_balance_id}) "
            "SET b.available_balance = $available_balance, b.current_balance = $current_balance, "
            "b.ledger_balance = $ledger_balance, b.accrued_interest = $accrued_interest "
            "MERGE (a)-[:HAS_BALANCE]->(b)",
            {
                "deposit_account_id": r["deposit_account_id"], "deposit_balance_id": r["deposit_balance_id"],
                "available_balance": r["available_balance"], "current_balance": r["current_balance"],
                "ledger_balance": r["ledger_balance"], "accrued_interest": r["accrued_interest"],
            },
        )
        for r in balances
    ]
    execute_cypher_batch(driver, cypher_bal)

    # 6. Load Loan Domain
    print("🏛️ Ingesting Loan Applications, Agreements & Collateral...")
    applications = run_psql_json("SELECT loan_application_id, customer_id, application_number, requested_amount, credit_score, application_status FROM financial.loan_application WHERE md_is_active = true")
    cypher_app = [
        (
            "MATCH (c:Customer {party_role_customer_id: $customer_id}) "
            "MERGE (app:LoanApplication {loan_application_id: $loan_application_id}) "
            "SET app.application_number = $application_number, app.requested_amount = $requested_amount, "
            "app.credit_score = $credit_score, app.status = $application_status "
            "MERGE (c)-[:APPLIED_FOR]->(app)",
            {
                "customer_id": r["customer_id"], "loan_application_id": r["loan_application_id"],
                "application_number": r["application_number"], "requested_amount": r["requested_amount"],
                "credit_score": r["credit_score"], "application_status": r["application_status"],
            },
        )
        for r in applications
    ]
    execute_cypher_batch(driver, cypher_app)

    loans = run_psql_json("SELECT loan_agreement_id, customer_id, loan_application_id, agreement_number, principal_amount, interest_rate, agreement_status, is_npl, currency_code FROM financial.loan_agreement WHERE md_is_active = true")
    cypher_loans = []
    for r in loans:
        cypher_loans.append((
            "MATCH (c:Customer {party_role_customer_id: $customer_id}) "
            "MERGE (l:LoanAgreement {loan_agreement_id: $loan_agreement_id}) "
            "SET l.agreement_number = $agreement_number, l.principal_amount = $principal_amount, "
            "l.interest_rate = $interest_rate, l.status = $agreement_status, l.is_npl = $is_npl, "
            "l.currency_code = $currency_code "
            "MERGE (c)-[:BORROWER_OF]->(l) "
            "WITH l MATCH (cur:RefCurrency {code: $currency_code}) MERGE (l)-[:DENOMINATED_IN]->(cur)",
            {
                "customer_id": r["customer_id"], "loan_agreement_id": r["loan_agreement_id"],
                "agreement_number": r["agreement_number"], "principal_amount": r["principal_amount"],
                "interest_rate": r["interest_rate"], "agreement_status": r["agreement_status"],
                "is_npl": bool(r["is_npl"]), "currency_code": r["currency_code"],
            },
        ))
        if r.get("loan_application_id"):
            cypher_loans.append((
                "MATCH (app:LoanApplication {loan_application_id: $loan_application_id}), "
                "(l:LoanAgreement {loan_agreement_id: $loan_agreement_id}) "
                "MERGE (app)-[:ORIGINATED]->(l)",
                {"loan_application_id": r["loan_application_id"], "loan_agreement_id": r["loan_agreement_id"]},
            ))
    execute_cypher_batch(driver, cypher_loans)

    collaterals = run_psql_json("SELECT loan_collateral_id, loan_agreement_id, collateral_type, estimated_value, ltv_ratio, collateral_status FROM financial.loan_collateral WHERE md_is_active = true")
    cypher_col = [
        (
            "MATCH (l:LoanAgreement {loan_agreement_id: $loan_agreement_id}) "
            "MERGE (col:LoanCollateral {loan_collateral_id: $loan_collateral_id}) "
            "SET col.collateral_type = $collateral_type, col.estimated_value = $estimated_value, "
            "col.ltv_ratio = $ltv_ratio, col.status = $collateral_status "
            "MERGE (l)-[:SECURED_BY]->(col)",
            {
                "loan_agreement_id": r["loan_agreement_id"], "loan_collateral_id": r["loan_collateral_id"],
                "collateral_type": r["collateral_type"], "estimated_value": r["estimated_value"],
                "ltv_ratio": r["ltv_ratio"], "collateral_status": r["collateral_status"],
            },
        )
        for r in collaterals
    ]
    execute_cypher_batch(driver, cypher_col)

    # 7. Print Knowledge Graph Inventory Summary
    print("\n✅ Knowledge Graph Build Complete!")
    print("📊 Graph Node & Relationship Summary:")

    with driver.session() as session:
        nodes = list(session.run("MATCH (n) RETURN labels(n)[0] AS label, count(n) AS node_count"))
        rels = list(session.run("MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS rel_count"))

        print("\n--- Nodes ---")
        for row in nodes:
            print(f"  • {row['label']}: {row['node_count']} nodes")

        print("\n--- Relationships ---")
        for row in rels:
            print(f"  • :{row['rel_type']}: {row['rel_count']} relationships")

    driver.close()

if __name__ == "__main__":
    main()
