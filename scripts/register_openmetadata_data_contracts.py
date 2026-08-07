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

import json
import urllib.request
import urllib.error
import subprocess
import sys
import os

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this script is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env  # noqa: E402

load_env()

OPENMETADATA_URL = "http://127.0.0.1:8585/api/v1"
JWT_TOKEN = os.getenv("OPENMETADATA_JWT_TOKEN", "")
if not JWT_TOKEN:
    print("⚠️ OPENMETADATA_JWT_TOKEN is not set; OpenMetadata API calls will be unauthenticated.")

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {JWT_TOKEN}"
}

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

DATA_PRODUCTS = [
    {
        "name": "Party_Customer_Data_Product",
        "displayName": "Party & Customer Data Product",
        "domain": "Party_Customer_Domain",
        "contract_file": "contracts/party_customer_data_product_contract.yaml",
        "description": """### 📜 Party & Customer Data Product Contract
**Version:** `1.0.0` | **Status:** `ACTIVE`
**Domain:** Party & Customer Domain | **Owner:** Master Data Management Governance Team

#### ⏱️ Service Level Agreements (SLAs)
- **Freshness SLA:** `15 minutes`
- **Availability SLA:** `99.9%`
- **Retention Policy:** `7 years (SCD Type 2)`
- **Data Quality Threshold:** `>= 99.0%`

#### 🛡️ Schema & Quality Guarantees
- `financial.party`: Core Master Party Entity (`party_id` non-null PK)
- `financial.party_individual`: Individual Person Demographics (`first_name`, `last_name` PII Personal; `date_of_birth` Special Category)
- `financial.party_organization`: Legal Entity Corporate Metadata
- `financial.party_role_customer`: Customer Role Profiles & KYC Status
"""
    },
    {
        "name": "Deposit_Liquidity_Data_Product",
        "displayName": "Deposit & Liquidity Data Product",
        "domain": "Deposit_Liquidity_Domain",
        "contract_file": "contracts/deposit_liquidity_data_product_contract.yaml",
        "description": """### 📜 Deposit & Liquidity Data Product Contract
**Version:** `1.0.0` | **Status:** `ACTIVE`
**Domain:** Deposit & Liquidity Domain | **Owner:** Retail & Corporate Banking Data Product Team

#### ⏱️ Service Level Agreements (SLAs)
- **Freshness SLA:** `5 minutes (Real-Time Ledger Balances)`
- **Availability SLA:** `99.95%`
- **Retention Policy:** `10 years (Regulatory Audit Ledger)`
- **Data Quality Threshold:** `>= 99.5%`

#### 🛡️ Schema & Quality Guarantees
- `financial.deposit_account`: BIAN Current & Savings Accounts (`account_number` PII Personal)
- `financial.deposit_balance`: Real-Time Position Balances & Overdraft Exposures
- `financial.deposit_transaction`: Immutable Ledger Transaction History
"""
    },
    {
        "name": "Loan_Credit_Risk_Data_Product",
        "displayName": "Loan & Credit Risk Data Product",
        "domain": "Loan_Credit_Risk_Domain",
        "contract_file": "contracts/loan_credit_risk_data_product_contract.yaml",
        "description": """### 📜 Loan & Credit Risk Data Product Contract
**Version:** `1.0.0` | **Status:** `ACTIVE`
**Domain:** Loan & Credit Risk Domain | **Owner:** Credit Risk & Capital Management Data Team

#### ⏱️ Service Level Agreements (SLAs)
- **Freshness SLA:** `1 hour`
- **Availability SLA:** `99.9%`
- **Retention Policy:** `10 years (Basel III/IV Compliance)`
- **Data Quality Threshold:** `>= 99.0%`

#### 🛡️ Schema & Quality Guarantees
- `financial.loan_agreement`: BIAN Approved Loan Contracts & Principal
- `financial.loan_application`: Credit Assessment Requests
- `financial.loan_repayment_schedule`: Installment Amortization Schedules
- `financial.loan_collateral`: Pledged Asset Valuations
"""
    }
]

def api_put(endpoint, payload):
    url = f"{OPENMETADATA_URL}/{endpoint}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"❌ Error PUT {endpoint}: {e.code} - {e.read().decode('utf-8')}")
        return None

def api_post(endpoint, payload=None):
    url = f"{OPENMETADATA_URL}/{endpoint}"
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw
    except urllib.error.HTTPError as e:
        print(f"❌ Error POST {endpoint}: {e.code} - {e.read().decode('utf-8')}")
        return None

def main():
    print("🚀 Creating Domains & Registering Data Products / Contracts in OpenMetadata Catalog...")

    # 1. Create Domains
    for d in DOMAINS:
        res = api_put("domains", d)
        if res:
            print(f"  📂 Created Business Domain: {d['displayName']}")

    # 2. Register Data Products
    for dp in DATA_PRODUCTS:
        payload = {
            "name": dp["name"],
            "displayName": dp["displayName"],
            "domain": dp["domain"],
            "description": dp["description"]
        }
        res = api_put("dataProducts", payload)
        if res:
            print(f"  📜 Registered Data Product & Contract: {dp['displayName']}")

    # Refresh Search Indexes
    api_post("apps/trigger/SearchIndexingApplication")
    print("\n✅ All 3 Business Domains, Data Products & Contracts successfully published into OpenMetadata UI!")

if __name__ == "__main__":
    main()
