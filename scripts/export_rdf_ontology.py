#!/usr/bin/env python3
"""
===============================================================================
RDF / OWL Ontology Exporter (PostgreSQL -> W3C Turtle .ttl)
===============================================================================
Exports relational database records from Supabase PostgreSQL (Port 54322) into
a standards-compliant W3C RDF Turtle (.ttl) Knowledge Graph instance file aligned
with FIBO (Financial Industry Business Ontology) and BIAN.
===============================================================================
"""

import json
import subprocess
import os

PG_CONTAINER = "supabase_db_ai-dataplatform"
OUTPUT_TTL = "ontology/instance_knowledge_graph.ttl"

def run_psql_json(sql_query):
    wrapped_sql = f"SELECT json_agg(t) FROM ({sql_query}) t;"
    cmd = [
        "docker", "exec", PG_CONTAINER,
        "psql", "-U", "postgres", "-d", "postgres", "-t", "-A", "-c", wrapped_sql
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not res.stdout.strip() or res.stdout.strip() == "[null]":
        return []
    return json.loads(res.stdout.strip())

def main():
    print("🚀 Exporting PostgreSQL data to RDF Turtle (.ttl)...")
    
    ttl_lines = [
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix fibo-party: <https://spec.edmcouncil.org/fibo/ontology/FND/Parties/Parties/> .",
        "@prefix fibo-loan: <https://spec.edmcouncil.org/fibo/ontology/LOAN/Loans/LoansGeneral/> .",
        "@prefix bian: <https://bian.org/ontology/v11/> .",
        "@prefix fin: <http://ai-platform.financial/ontology/v1#> .",
        "@prefix data: <http://ai-platform.financial/resource/> .",
        ""
    ]

    # 1. Export Customers
    customers = run_psql_json("SELECT party_role_customer_id, customer_number, customer_segment, aml_risk_rating, kyc_status FROM financial.party_role_customer WHERE md_is_active = true LIMIT 500")
    print(f"  • Exporting {len(customers)} Customer RDF instances...")
    for c in customers:
        cid = c['party_role_customer_id']
        ttl_lines.append(f"data:customer_{cid} a fin:Customer ;")
        ttl_lines.append(f"    fin:customerNumber \"{c['customer_number']}\" ;")
        ttl_lines.append(f"    fin:customerSegment \"{c['customer_segment']}\" ;")
        ttl_lines.append(f"    fin:amlRiskRating \"{c['aml_risk_rating']}\" ;")
        ttl_lines.append(f"    fin:kycStatus \"{c['kyc_status']}\" .")
        ttl_lines.append("")

    # 2. Export Deposit Accounts
    accounts = run_psql_json("SELECT deposit_account_id, customer_id, account_number, account_type, currency_code FROM financial.deposit_account WHERE md_is_active = true LIMIT 500")
    print(f"  • Exporting {len(accounts)} DepositAccount RDF instances...")
    for a in accounts:
        aid = a['deposit_account_id']
        cid = a['customer_id']
        ttl_lines.append(f"data:account_{aid} a fin:DepositAccount ;")
        ttl_lines.append(f"    fin:accountNumber \"{a['account_number']}\" ;")
        ttl_lines.append(f"    fin:accountType \"{a['account_type']}\" ;")
        ttl_lines.append(f"    fin:currencyCode \"{a['currency_code']}\" .")
        ttl_lines.append(f"data:customer_{cid} fin:holdsAccount data:account_{aid} .")
        ttl_lines.append("")

    # 3. Export Loan Agreements
    loans = run_psql_json("SELECT loan_agreement_id, customer_id, agreement_number, principal_amount, interest_rate, is_npl FROM financial.loan_agreement WHERE md_is_active = true LIMIT 500")
    print(f"  • Exporting {len(loans)} LoanAgreement RDF instances...")
    for l in loans:
        lid = l['loan_agreement_id']
        cid = l['customer_id']
        npl_bool = "true" if l['is_npl'] else "false"
        ttl_lines.append(f"data:loan_{lid} a fin:LoanAgreement ;")
        ttl_lines.append(f"    fin:agreementNumber \"{l['agreement_number']}\" ;")
        ttl_lines.append(f"    fin:principalAmount {l['principal_amount']} ;")
        ttl_lines.append(f"    fin:interestRate {l['interest_rate']} ;")
        ttl_lines.append(f"    fin:isNpl {npl_bool}^^xsd:boolean .")
        ttl_lines.append(f"data:customer_{cid} fin:borrowerOf data:loan_{lid} .")
        ttl_lines.append("")

    os.makedirs("ontology", exist_ok=True)
    with open(OUTPUT_TTL, "w") as f:
        f.write("\n".join(ttl_lines))

    print(f"✅ RDF Turtle export completed successfully! Output saved to: {OUTPUT_TTL}")

if __name__ == "__main__":
    main()
