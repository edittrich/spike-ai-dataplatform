#!/usr/bin/env python3
"""
===============================================================================
OpenMetadata Data Product & Data Contract Registration Script
===============================================================================
1. Creates Business Domains (Party & Customer, Deposit & Liquidity, Loan & Credit Risk).
2. Registers the 3 Enterprise Data Products in OpenMetadata Catalog:
  - Party & Customer Data Product
  - Deposit & Liquidity Data Product
  - Loan & Credit Risk Data Product
3. Attaches formal Data Contract specifications (SLAs, Quality Thresholds, Schema Contracts)
   directly to each Data Product entity.
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
from scripts._openmetadata_client import api_put, api_post  # noqa: E402
from scripts._contracts import load_contracts, render_contract_markdown  # noqa: E402

DOMAINS = [
    {
        "name": "Party_Customer_Domain",
        "displayName": "Party & Customer Domain",
        "description": "Master Party, Individual, Organization, and Customer Role domain aligned with BIAN & FIBO standards.",
        "domainType": "Aggregate"
    },
    {
        "name": "Deposit_Liquidity_Domain",
        "displayName": "Deposit & Liquidity Domain",
        "description": "Current & Savings Deposit Accounts, Position Balances, and Ledger Transactions.",
        "domainType": "Aggregate"
    },
    {
        "name": "Loan_Credit_Risk_Domain",
        "displayName": "Loan & Credit Risk Domain",
        "description": "Loan Products, Credit Applications, Amortization Schedules, and Pledged Collateral Assets.",
        "domainType": "Aggregate"
    }
]

# D2 fix: this list now only carries the OpenMetadata-entity identity fields
# (name/displayName/domain/contract_file) -- the "description" markdown that
# used to be hand-duplicated here per product is generated at registration
# time from the real contracts/*.yaml content via render_contract_markdown(),
# so contracts/*.yaml is the actual single source of truth, not a third,
# independently-maintained copy of it.
DATA_PRODUCTS = [
    {
        "name": "Party_Customer_Data_Product",
        "displayName": "Party & Customer Data Product",
        "domain": "Party_Customer_Domain",
        "contract_file": "contracts/party_customer_data_product_contract.yaml",
    },
    {
        "name": "Deposit_Liquidity_Data_Product",
        "displayName": "Deposit & Liquidity Data Product",
        "domain": "Deposit_Liquidity_Domain",
        "contract_file": "contracts/deposit_liquidity_data_product_contract.yaml",
    },
    {
        "name": "Loan_Credit_Risk_Data_Product",
        "displayName": "Loan & Credit Risk Data Product",
        "domain": "Loan_Credit_Risk_Domain",
        "contract_file": "contracts/loan_credit_risk_data_product_contract.yaml",
    },
]

def main() -> None:
    """Creates the 3 BIAN/FIBO domain entities (DOMAINS) and registers each
    data product's description, generated from the real contracts/*.yaml
    content (D2: previously hand-duplicated markdown that could -- and did --
    drift from the YAML; now the YAML is parsed and rendered, not copied)."""
    print("🚀 Creating Domains & Registering Data Products / Contracts in OpenMetadata Catalog...")

    # Parse contracts/*.yaml once, keyed by their own source-file path so
    # each DATA_PRODUCTS entry's hand-specified "contract_file" can look its
    # matching parsed contract back up.
    contracts_by_file = {c["_source_file"]: c for c in load_contracts()}

    # 1. Create Domains
    for d in DOMAINS:
        res = api_put("domains", d)
        if res:
            print(f"  📂 Created Business Domain: {d['displayName']}")

    # 2. Register Data Products
    for dp in DATA_PRODUCTS:
        contract = contracts_by_file[dp["contract_file"]]
        payload = {
            "name": dp["name"],
            "displayName": dp["displayName"],
            "domain": dp["domain"],
            "description": render_contract_markdown(contract),
        }
        res = api_put("dataProducts", payload)
        if res:
            print(f"  📜 Registered Data Product & Contract: {dp['displayName']}")

    # Refresh Search Indexes
    api_post("apps/trigger/SearchIndexingApplication")
    print("\n✅ All 3 Business Domains, Data Products & Contracts successfully published into OpenMetadata UI!")

if __name__ == "__main__":
    main()
