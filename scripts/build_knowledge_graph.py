#!/usr/bin/env python3
"""
===============================================================================
Knowledge Graph Construction Pipeline (PostgreSQL -> Neo4j)
===============================================================================
Extracts BIAN/FIBO aligned relational entities from PostgreSQL (Port 54322)
and instantiates a Knowledge Graph in Neo4j (Port 7474/7687).
===============================================================================
"""

import json
import os
import subprocess
import urllib.request
import urllib.error
import base64
import sys

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this script is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env  # noqa: E402

load_env()

# Connection Configs
PG_CONTAINER = "supabase_db_ai-dataplatform"
NEO4J_URL = "http://127.0.0.1:7474/db/neo4j/tx/commit"
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "")

auth_header = base64.b64encode(f"{NEO4J_USER}:{NEO4J_PASS}".encode()).decode()

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

def execute_cypher_batch(statements):
    """Executes a list of Cypher statements in Neo4j via HTTP API."""
    if not statements:
        return
    payload = json.dumps({"statements": [{"statement": stmt} for stmt in statements]}).encode('utf-8')
    req = urllib.request.Request(
        NEO4J_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_header}"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get("errors"):
                print(f"Cypher Error: {data['errors']}")
    except Exception as e:
        print(f"Failed to execute Cypher: {e}")

def main():
    print("🚀 Starting Knowledge Graph Sync (PostgreSQL -> Neo4j)...")

    # 1. Clear existing database for clean reload
    print("🧹 Cleaning existing Neo4j graph...")
    execute_cypher_batch(["MATCH (n) DETACH DELETE n"])

    # 2. Setup Uniqueness Constraints & Indexes
    print("⚡ Setting up Constraints & Indexes...")
    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Party) REQUIRE p.party_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Customer) REQUIRE c.party_role_customer_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (a:DepositAccount) REQUIRE a.deposit_account_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (l:LoanAgreement) REQUIRE l.loan_agreement_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (rc:RefCountry) REQUIRE rc.code IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (rcur:RefCurrency) REQUIRE rcur.code IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (rind:RefIndustry) REQUIRE rind.code IS UNIQUE"
    ]
    execute_cypher_batch(constraints)

    # 3. Load Reference Data (Currencies, Countries, Industries)
    print("🌐 Ingesting Reference Ontologies...")
    currencies = run_psql_json("SELECT currency_code, currency_name, symbol FROM ref.ref_currency")
    cypher_cur = []
    for r in currencies:
        sym_clean = r['symbol'].replace("'", "\\'") if r.get('symbol') else ""
        cypher_cur.append(f"MERGE (c:RefCurrency {{code: '{r['currency_code']}'}}) SET c.name = '{r['currency_name']}', c.symbol = '{sym_clean}'")
    execute_cypher_batch(cypher_cur)

    countries = run_psql_json("SELECT country_code, country_name, is_high_risk_aml FROM ref.ref_country")
    cypher_cnt = []
    for r in countries:
        name_clean = r['country_name'].replace("'", "\\'")
        risk_str = str(r['is_high_risk_aml']).lower()
        cypher_cnt.append(f"MERGE (c:RefCountry {{code: '{r['country_code']}'}}) SET c.name = '{name_clean}', c.is_high_risk_aml = {risk_str}")
    execute_cypher_batch(cypher_cnt)

    industries = run_psql_json("SELECT nace_code, nace_title, risk_level FROM ref.ref_nace_industry")
    cypher_ind = []
    for r in industries:
        title_clean = r['nace_title'].replace("'", "\\'")
        cypher_ind.append(f"MERGE (i:RefIndustry {{code: '{r['nace_code']}'}}) SET i.title = '{title_clean}', i.risk_level = '{r['risk_level']}'")
    execute_cypher_batch(cypher_ind)

    # 4. Load Core Parties & Roles
    print("👤 Ingesting Core Parties & Customer Roles...")
    parties = run_psql_json("SELECT party_id, party_bk, party_type, status_code FROM financial.party WHERE md_is_active = true")
    cypher_parties = []
    for r in parties:
        cypher_parties.append(f"MERGE (p:Party {{party_id: '{r['party_id']}'}}) SET p.party_bk = '{r['party_bk']}', p.type = '{r['party_type']}', p.status = '{r['status_code']}'")
    execute_cypher_batch(cypher_parties)

    individuals = run_psql_json("SELECT party_id, first_name, last_name, gender, citizenship_country_code FROM financial.party_individual WHERE md_is_active = true")
    cypher_indiv = []
    for r in individuals:
        fn = r['first_name'].replace("'", "\\'")
        ln = r['last_name'].replace("'", "\\'")
        cypher_indiv.append(
            f"MATCH (p:Party {{party_id: '{r['party_id']}'}}) "
            f"SET p:Individual, p.first_name = '{fn}', p.last_name = '{ln}', p.gender = '{r['gender']}' "
            f"WITH p MATCH (c:RefCountry {{code: '{r['citizenship_country_code']}'}}) MERGE (p)-[:CITIZEN_OF]->(c)"
        )
    execute_cypher_batch(cypher_indiv)

    orgs = run_psql_json("SELECT party_id, legal_name, registration_number, nace_code FROM financial.party_organization WHERE md_is_active = true")
    cypher_orgs = []
    for r in orgs:
        ln = r['legal_name'].replace("'", "\\'")
        cypher_orgs.append(
            f"MATCH (p:Party {{party_id: '{r['party_id']}'}}) "
            f"SET p:Organization, p.legal_name = '{ln}', p.registration_number = '{r['registration_number']}' "
            f"WITH p MATCH (i:RefIndustry {{code: '{r['nace_code']}'}}) MERGE (p)-[:OPERATES_IN_INDUSTRY]->(i)"
        )
    execute_cypher_batch(cypher_orgs)

    customers = run_psql_json("SELECT party_role_customer_id, party_id, customer_number, customer_segment, kyc_status, aml_risk_rating FROM financial.party_role_customer WHERE md_is_active = true")
    cypher_cust = []
    for r in customers:
        cypher_cust.append(
            f"MATCH (p:Party {{party_id: '{r['party_id']}'}}) "
            f"MERGE (c:Customer {{party_role_customer_id: '{r['party_role_customer_id']}'}}) "
            f"SET c.customer_number = '{r['customer_number']}', c.segment = '{r['customer_segment']}', c.kyc_status = '{r['kyc_status']}', c.aml_risk_rating = '{r['aml_risk_rating']}' "
            f"MERGE (p)-[:PLAYS_ROLE]->(c)"
        )
    execute_cypher_batch(cypher_cust)

    # 5. Load Deposit Domain
    print("💳 Ingesting Deposit Accounts & Balances...")
    accounts = run_psql_json("SELECT deposit_account_id, customer_id, account_number, account_type, account_status, currency_code FROM financial.deposit_account WHERE md_is_active = true")
    cypher_acc = []
    for r in accounts:
        cypher_acc.append(
            f"MATCH (c:Customer {{party_role_customer_id: '{r['customer_id']}'}}) "
            f"MERGE (a:DepositAccount {{deposit_account_id: '{r['deposit_account_id']}'}}) "
            f"SET a.account_number = '{r['account_number']}', a.account_type = '{r['account_type']}', a.account_status = '{r['account_status']}', a.currency_code = '{r['currency_code']}' "
            f"MERGE (c)-[:HOLDS_ACCOUNT]->(a) "
            f"WITH a MATCH (cur:RefCurrency {{code: '{r['currency_code']}'}}) MERGE (a)-[:DENOMINATED_IN]->(cur)"
        )
    execute_cypher_batch(cypher_acc)

    balances = run_psql_json("SELECT deposit_balance_id, deposit_account_id, available_balance, current_balance, ledger_balance, accrued_interest FROM financial.deposit_balance WHERE md_is_active = true")
    cypher_bal = []
    for r in balances:
        cypher_bal.append(
            f"MATCH (a:DepositAccount {{deposit_account_id: '{r['deposit_account_id']}'}}) "
            f"MERGE (b:DepositBalance {{deposit_balance_id: '{r['deposit_balance_id']}'}}) "
            f"SET b.available_balance = {r['available_balance']}, b.current_balance = {r['current_balance']}, b.ledger_balance = {r['ledger_balance']}, b.accrued_interest = {r['accrued_interest']} "
            f"MERGE (a)-[:HAS_BALANCE]->(b)"
        )
    execute_cypher_batch(cypher_bal)

    # 6. Load Loan Domain
    print("🏛️ Ingesting Loan Applications, Agreements & Collateral...")
    applications = run_psql_json("SELECT loan_application_id, customer_id, application_number, requested_amount, credit_score, application_status FROM financial.loan_application WHERE md_is_active = true")
    cypher_app = []
    for r in applications:
        cypher_app.append(
            f"MATCH (c:Customer {{party_role_customer_id: '{r['customer_id']}'}}) "
            f"MERGE (app:LoanApplication {{loan_application_id: '{r['loan_application_id']}'}}) "
            f"SET app.application_number = '{r['application_number']}', app.requested_amount = {r['requested_amount']}, app.credit_score = {r['credit_score']}, app.status = '{r['application_status']}' "
            f"MERGE (c)-[:APPLIED_FOR]->(app)"
        )
    execute_cypher_batch(cypher_app)

    loans = run_psql_json("SELECT loan_agreement_id, customer_id, loan_application_id, agreement_number, principal_amount, interest_rate, agreement_status, is_npl, currency_code FROM financial.loan_agreement WHERE md_is_active = true")
    cypher_loans = []
    for r in loans:
        npl_str = str(r['is_npl']).lower()
        cypher_loans.append(
            f"MATCH (c:Customer {{party_role_customer_id: '{r['customer_id']}'}}) "
            f"MERGE (l:LoanAgreement {{loan_agreement_id: '{r['loan_agreement_id']}'}}) "
            f"SET l.agreement_number = '{r['agreement_number']}', l.principal_amount = {r['principal_amount']}, l.interest_rate = {r['interest_rate']}, l.status = '{r['agreement_status']}', l.is_npl = {npl_str}, l.currency_code = '{r['currency_code']}' "
            f"MERGE (c)-[:BORROWER_OF]->(l) "
            f"WITH l MATCH (cur:RefCurrency {{code: '{r['currency_code']}'}}) MERGE (l)-[:DENOMINATED_IN]->(cur)"
        )
        if r.get('loan_application_id'):
            cypher_loans.append(
                f"MATCH (app:LoanApplication {{loan_application_id: '{r['loan_application_id']}'}}), (l:LoanAgreement {{loan_agreement_id: '{r['loan_agreement_id']}'}}) "
                f"MERGE (app)-[:ORIGINATED]->(l)"
            )
    execute_cypher_batch(cypher_loans)

    collaterals = run_psql_json("SELECT loan_collateral_id, loan_agreement_id, collateral_type, estimated_value, ltv_ratio, collateral_status FROM financial.loan_collateral WHERE md_is_active = true")
    cypher_col = []
    for r in collaterals:
        cypher_col.append(
            f"MATCH (l:LoanAgreement {{loan_agreement_id: '{r['loan_agreement_id']}'}}) "
            f"MERGE (col:LoanCollateral {{loan_collateral_id: '{r['loan_collateral_id']}'}}) "
            f"SET col.collateral_type = '{r['collateral_type']}', col.estimated_value = {r['estimated_value']}, col.ltv_ratio = {r['ltv_ratio']}, col.status = '{r['collateral_status']}' "
            f"MERGE (l)-[:SECURED_BY]->(col)"
        )
    execute_cypher_batch(cypher_col)

    # 7. Print Knowledge Graph Inventory Summary
    print("\n✅ Knowledge Graph Build Complete!")
    print("📊 Graph Node & Relationship Summary:")
    
    summary_cypher = [
        "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS node_count",
        "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS rel_count"
    ]
    payload = json.dumps({"statements": [{"statement": stmt} for stmt in summary_cypher]}).encode('utf-8')
    req = urllib.request.Request(NEO4J_URL, data=payload, headers={"Content-Type": "application/json", "Authorization": f"Basic {auth_header}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        res = json.loads(resp.read().decode('utf-8'))
        nodes = res['results'][0]['data']
        rels = res['results'][1]['data']
        
        print("\n--- Nodes ---")
        for row in nodes:
            print(f"  • {row['row'][0]}: {row['row'][1]} nodes")
            
        print("\n--- Relationships ---")
        for row in rels:
            print(f"  • :{row['row'][0]}: {row['row'][1]} relationships")

if __name__ == "__main__":
    main()
