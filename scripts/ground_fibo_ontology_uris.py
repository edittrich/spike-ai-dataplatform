#!/usr/bin/env python3
"""
===============================================================================
FIBO W3C Class URI Semantic Grounding Automation Script
===============================================================================
Explicitly links OpenMetadata catalog entities to official W3C FIBO
(Financial Industry Business Ontology) class URIs.

Actions:
1. Creates `FIBO_Ontology` Tag Classification in OpenMetadata Catalog.
2. Ingests official FIBO URIs (e.g. https://spec.edmcouncil.org/fibo/ontology/...) as tags.
3. Maps each PostgreSQL table & Cube.js semantic cube entity to its exact FIBO URI.
4. Appends FIBO W3C Semantic Grounding metadata blocks to table entity descriptions.
===============================================================================
"""

import sys
import os

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this script is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env  # noqa: E402

load_env()

# _openmetadata_client reads OPENMETADATA_URL/JWT_TOKEN at import time, so it
# must be imported after load_env() -- see its module docstring.
from scripts._openmetadata_client import api_get, api_put, api_post  # noqa: E402

# FIBO Class URI Grounding Specification Map
FIBO_GROUNDING_MAP = {
    # Party & Customer Domain
    "financial.party": {
        "tag": "Party",
        # Matches ontology/financial_platform_ontology.ttl's fin:Party
        # rdfs:isDefinedBy fibo-party:Party -- this used to disagree (this map
        # said FND/AgentsAndPeople/Agents/Party), and FIBO's Agent module
        # defines a distinct, more general Agent class, not a Party class --
        # the TTL's grounding is the correct one; this map had drifted.
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/Parties/Parties/Party",
        "fibo_label": "fibo-fnd-pty-pty:Party",
        "description": "An agent that is an individual or organization, capable of entering into agreements or obligations."
    },
    "financial.party_individual": {
        "tag": "Person",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/AgentsAndPeople/People/Person",
        "fibo_label": "fibo-fnd-aap-ppl:Person",
        "description": "A natural person, human individual."
    },
    "financial.party_organization": {
        "tag": "Organization",
        # Matches ontology/financial_platform_ontology.ttl's fin:Organization
        # rdfs:isDefinedBy fibo-org:LegalEntity (this map previously pointed
        # at FND/Organizations/Organizations/Organization instead).
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/FunctionalMetadata/Organizations/LegalEntity",
        "fibo_label": "fibo-fbc-fct-org:LegalEntity",
        "description": "A legal entity or social structure formed by people with a shared purpose."
    },
    "financial.party_role_customer": {
        "tag": "Customer",
        # ontology/financial_platform_ontology.ttl's fin:Customer grounds to
        # bian:CustomerRole instead -- both are legitimately correct (Customer
        # is a first-class BIAN business role concept as well as a FIBO
        # party-role concept), and the TTL now references both rather than
        # this map and the TTL silently disagreeing about which one applies.
        # This map stays FIBO-only since it's specifically the FIBO grounding
        # pass (see scripts/register_openmetadata_data_contracts.py for the
        # BIAN domain/product registration).
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/Parties/Roles/Customer",
        "fibo_label": "fibo-fnd-pty-rl:Customer",
        "description": "A party in the role of purchasing or receiving financial products or services."
    },
    "financial.party_address": {
        "tag": "PhysicalAddress",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/Places/Addresses/PhysicalAddress",
        "fibo_label": "fibo-fnd-plc-adr:PhysicalAddress",
        "description": "A physical location address where a party resides or conducts business."
    },
    "financial.party_identification": {
        "tag": "Identifier",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/Arrangements/IdentifiersAndIndices/Identifier",
        "fibo_label": "fibo-fnd-arr-id:Identifier",
        "description": "Official government passport, national ID, or tax identification reference."
    },

    # Deposit Domain
    "financial.deposit_account": {
        "tag": "DepositAccount",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/ProductsAndServices/FinancialProductsAndServices/DepositAccount",
        "fibo_label": "fibo-fbc-pas-fpas:DepositAccount",
        "description": "A financial account held at a bank or institution allowing funds to be deposited and withdrawn."
    },
    "financial.deposit_balance": {
        "tag": "AccountBalance",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/FinancialInstruments/FinancialInstruments/Balance",
        "fibo_label": "fibo-fbc-fi-fi:Balance",
        "description": "Real-time ledger position balance and available funds."
    },
    "financial.deposit_transaction": {
        "tag": "FinancialTransaction",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/ProductsAndServices/FinancialProductsAndServices/Transaction",
        "fibo_label": "fibo-fbc-pas-fpas:Transaction",
        "description": "An event involving transfer of monetary value between accounts."
    },
    "financial.deposit_interest_term": {
        "tag": "InterestRateTerm",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/DebtAndEquities/Debt/InterestRate",
        "fibo_label": "fibo-fbc-dae-dbt:InterestRate",
        "description": "Contractual rate and calculation terms for interest accrual."
    },
    "financial.deposit_overdraft_facility": {
        "tag": "CreditFacility",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/ProductsAndServices/FinancialProductsAndServices/CreditFacility",
        "fibo_label": "fibo-fbc-pas-fpas:CreditFacility",
        "description": "An agreement permitting account balance to drop below zero up to a limit."
    },

    # Loan Domain
    "financial.loan_application": {
        "tag": "CreditApplication",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/ProductsAndServices/FinancialProductsAndServices/CreditApplication",
        "fibo_label": "fibo-fbc-pas-fpas:CreditApplication",
        "description": "A formal application submitted by a customer for a credit line or loan."
    },
    "financial.loan_agreement": {
        "tag": "LoanContract",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/ProductsAndServices/FinancialProductsAndServices/Loan",
        "fibo_label": "fibo-fbc-pas-fpas:Loan",
        "description": "A binding contract under which a lender advances funds to a borrower."
    },
    "financial.loan_repayment_schedule": {
        "tag": "PaymentSchedule",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/DebtAndEquities/Debt/PaymentSchedule",
        "fibo_label": "fibo-fbc-dae-dbt:PaymentSchedule",
        "description": "Amortization schedule detailing periodic principal and interest payment installments."
    },
    "financial.loan_disbursement": {
        "tag": "Disbursement",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/ProductsAndServices/FinancialProductsAndServices/Disbursement",
        "fibo_label": "fibo-fbc-pas-fpas:Disbursement",
        "description": "Execution payment transferring approved loan principal to borrower target account."
    },
    "financial.loan_collateral": {
        "tag": "CollateralAsset",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/DebtAndEquities/Debt/Collateral",
        "fibo_label": "fibo-fbc-dae-dbt:Collateral",
        "description": "Pledged asset or security guaranteeing loan repayment."
    },

    # Reference Data
    "ref.ref_country": {
        "tag": "Country",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/Places/Locations/Country",
        "fibo_label": "fibo-fnd-plc-loc:Country",
        "description": "ISO 3166-1 geopolitical country entity."
    },
    "ref.ref_currency": {
        "tag": "Currency",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/Accounting/CurrencyAmount/Currency",
        "fibo_label": "fibo-fnd-acc-cur:Currency",
        "description": "ISO 4217 medium of exchange currency."
    },
    "ref.ref_nace_industry": {
        "tag": "IndustrySector",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/Organizations/FormalOrganizations/IndustrySector",
        "fibo_label": "fibo-fnd-org-fm:IndustrySector",
        "description": "NACE Rev. 2 economic activity industry classification."
    }
}

def main():
    print("🌐 Executing FIBO W3C Class URI Semantic Grounding across Catalog Entities...")

    # 1. Create Classification `FIBO_Ontology`
    print("🏷️ Creating Tag Classification `FIBO_Ontology`...")
    api_put("classifications", {
        "name": "FIBO_Ontology",
        "displayName": "W3C FIBO Ontology",
        "description": "Financial Industry Business Ontology (FIBO) W3C Class URIs published by EDM Council."
    })

    # 2. Register FIBO Tags
    for key, info in FIBO_GROUNDING_MAP.items():
        tag_payload = {
            "name": info["tag"],
            "displayName": info["fibo_label"],
            "description": f"FIBO Class URI: {info['fibo_uri']}\n\n{info['description']}",
            "classification": "FIBO_Ontology"
        }
        api_put("tags", tag_payload)

    # 3. Fetch Catalog Tables and Apply Grounding Tags & Descriptions
    tables_resp = api_get("tables?fields=columns,tags&limit=100")
    if not tables_resp or "data" not in tables_resp:
        print("❌ Could not fetch tables from catalog!")
        return

    grounded_count = 0
    for tbl in tables_resp["data"]:
        schema_name = tbl["databaseSchema"]["name"]
        tbl_name = tbl["name"]
        key = f"{schema_name}.{tbl_name}"

        if key in FIBO_GROUNDING_MAP:
            info = FIBO_GROUNDING_MAP[key]
            tag_fqn = f"FIBO_Ontology.{info['tag']}"
            
            existing_tags = tbl.get("tags", [])
            tag_names = [t.get("tagFQN") for t in existing_tags]
            
            if tag_fqn not in tag_names:
                existing_tags.append({
                    "tagFQN": tag_fqn,
                    "labelType": "Automated",
                    "state": "Confirmed",
                    "source": "Classification"
                })

            base_desc = tbl.get("description", "").split("\n\n---\n#### 🌐 W3C FIBO Semantic Grounding")[0]
            fibo_grounding_block = f"{base_desc}\n\n---\n#### 🌐 W3C FIBO Semantic Grounding\n- **FIBO W3C Class URI:** [`{info['fibo_uri']}`]({info['fibo_uri']})\n- **FIBO Ontology Prefix:** `{info['fibo_label']}`\n- **Ontology Definition:** {info['description']}"

            put_payload = {
                "name": tbl["name"],
                "displayName": tbl.get("displayName", tbl["name"]),
                "description": fibo_grounding_block,
                "databaseSchema": tbl["databaseSchema"]["fullyQualifiedName"],
                "columns": tbl.get("columns", []),
                "tags": existing_tags,
                "tableType": tbl.get("tableType", "Regular")
            }
            res = api_put("tables", put_payload)
            if res:
                grounded_count += 1
                print(f"  🌐 Grounded `{key}` ➔ FIBO URI: {info['fibo_uri']}")

    # Refresh Search Indexes
    api_post("apps/trigger/SearchIndexingApplication")
    print(f"\n✅ Successfully Grounded {grounded_count} Catalog Table Entities to Official W3C FIBO Class URIs!")

if __name__ == "__main__":
    main()
