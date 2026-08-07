#!/usr/bin/env python3
"""
===============================================================================
End-to-End Lineage Sync Automation Script
===============================================================================
Connects the 3 core layers of the platform:
  [Tier 1: PostgreSQL Tables] ➔ [Tier 2: Cube.js Semantic Cubes] ➔ [Tier 3: Neo4j Knowledge Graph]

Actions:
1. Registers Cube.js Semantic Layer entities in OpenMetadata Catalog.
2. Ingests 3-tier lineage edges into OpenMetadata Catalog Lineage API (`PUT /api/v1/lineage`).
3. Seeds Meta-Lineage graph nodes & relationships into Neo4j Knowledge Graph.
4. Triggers OpenSearch reindexing so Lineage DAG graphs render cleanly in OpenMetadata UI.
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

# Lineage Mapping Definition (Table -> Semantic Cube -> Knowledge Graph Node)
LINEAGE_MAP = [
    # Party & Customer Domain
    ("financial", "party", "Cube_Party", "Party", "Core Master Party Entity"),
    ("financial", "party_individual", "Cube_PartyIndividual", "Individual", "Demographic Individual Person"),
    ("financial", "party_organization", "Cube_PartyOrganization", "Organization", "Corporate Legal Entity"),
    ("financial", "party_role_customer", "Cube_PartyRoleCustomer", "Customer", "Verified Customer Role"),
    ("financial", "party_address", "Cube_PartyAddress", "Address", "Geographic Address Location"),
    ("financial", "party_identification", "Cube_PartyIdentification", "Identification", "Official Passport/Tax ID"),

    # Deposit Domain
    ("financial", "deposit_account", "Cube_DepositAccount", "DepositAccount", "BIAN Deposit Account"),
    ("financial", "deposit_balance", "Cube_DepositBalance", "DepositBalance", "Real-Time Balance Position"),
    ("financial", "deposit_transaction", "Cube_DepositTransaction", "DepositTransaction", "Ledger Transaction Entry"),
    ("financial", "deposit_interest_term", "Cube_DepositInterestTerm", "DepositInterestTerm", "Interest Accrual Rule"),
    ("financial", "deposit_overdraft_facility", "Cube_DepositOverdraftFacility", "DepositOverdraftFacility", "Overdraft Facility Terms"),

    # Loan Domain
    ("financial", "loan_application", "Cube_LoanApplication", "LoanApplication", "Credit Application Request"),
    ("financial", "loan_agreement", "Cube_LoanAgreement", "LoanAgreement", "Approved Loan Principal Contract"),
    ("financial", "loan_repayment_schedule", "Cube_LoanRepaymentSchedule", "LoanRepaymentSchedule", "Installment Amortization"),
    ("financial", "loan_disbursement", "Cube_LoanDisbursement", "LoanDisbursement", "Fund Disbursement Execution"),
    ("financial", "loan_collateral", "Cube_LoanCollateral", "LoanCollateral", "Pledged Collateral Asset"),

    # Reference ISO Domain
    ("ref", "ref_country", "Cube_RefCountry", "RefCountry", "ISO 3166 Country Reference"),
    ("ref", "ref_currency", "Cube_RefCurrency", "RefCurrency", "ISO 4217 Currency Reference"),
    ("ref", "ref_nace_industry", "Cube_RefNaceIndustry", "RefIndustry", "NACE Rev. 2 Industry Reference")
]

def api_get(endpoint):
    url = f"{OPENMETADATA_URL}/{endpoint}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"❌ Error GET {endpoint}: {e.code} - {e.read().decode('utf-8')}")
        return None

def api_put(endpoint, payload):
    url = f"{OPENMETADATA_URL}/{endpoint}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {"status": "success"}
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"status": "success", "raw": raw}
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

def run_cypher(statement):
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_pass = os.getenv("NEO4J_PASSWORD", "")
    cmd = [
        "docker", "exec", "neo4j_knowledge_graph", "cypher-shell",
        "-u", neo4j_user, "-p", neo4j_pass, statement
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout.strip()

def sync_openmetadata_lineage():
    print("\n🔗 Phase 1: OpenMetadata Catalog End-to-End Lineage Sync")
    print("---------------------------------------------------------")

    tables_resp = api_get("tables?limit=100")
    if not tables_resp or "data" not in tables_resp:
        print("❌ Could not fetch tables from catalog!")
        return

    table_id_map = {}
    for tbl in tables_resp["data"]:
        fqn = tbl["fullyQualifiedName"]
        table_id_map[fqn] = tbl["id"]

    # Register Semantic Layer Cubes
    print("📦 Registering Cube.js Semantic Engine in Catalog...")
    api_put("services/databaseServices", {
        "name": "Cube_Semantic_Engine",
        "serviceType": "CustomDatabase",
        "description": "Cube.js Open-Source Semantic Layer mapping business metrics and dimensions.",
        "connection": {"config": {"type": "CustomDatabase"}}
    })
    api_put("databases", {
        "name": "semantic_layer",
        "service": "Cube_Semantic_Engine",
        "description": "Semantic Metric Cubes and Views."
    })
    api_put("databaseSchemas", {
        "name": "cubes",
        "database": "Cube_Semantic_Engine.semantic_layer",
        "description": "BIAN & FIBO Aligned Semantic Data Cubes."
    })

    cube_id_map = {}
    for schema, tbl_name, cube_name, kg_entity, desc in LINEAGE_MAP:
        cube_payload = {
            "name": cube_name,
            "displayName": f"Cube.{cube_name}",
            "description": f"Cube.js Semantic Cube for {desc}",
            "databaseSchema": "Cube_Semantic_Engine.semantic_layer.cubes",
            "columns": [
                {"name": "measure_count", "dataType": "BIGINT", "description": "Row/Entity count metric"},
                {"name": "dimension_id", "dataType": "UUID", "description": "Primary dimension key"}
            ],
            "tableType": "View"
        }
        res = api_put("tables", cube_payload)
        if res and "id" in res:
            cube_id_map[cube_name] = res["id"]

    # Create Lineage Edges (PostgreSQL Table -> Cube.js Cube)
    edge_count = 0
    for schema, tbl_name, cube_name, kg_entity, desc in LINEAGE_MAP:
        pg_fqn = f"PostgreSQL_Financial_Platform.postgres.{schema}.{tbl_name}"
        from_id = table_id_map.get(pg_fqn)
        to_id = cube_id_map.get(cube_name)

        if from_id and to_id:
            lineage_payload = {
                "edge": {
                    "fromEntity": {"id": from_id, "type": "table"},
                    "toEntity": {"id": to_id, "type": "table"},
                    "lineageDetails": {
                        "description": f"Derives semantic metrics from physical table `{schema}.{tbl_name}` into `{cube_name}`"
                    }
                }
            }
            res = api_put("lineage", lineage_payload)
            if res:
                edge_count += 1
                print(f"  🔗 Connected Lineage: {schema}.{tbl_name} ➔ Cube.{cube_name}")

    print(f"✅ OpenMetadata Lineage Sync Complete: Created {edge_count} 3-Tier Lineage Edges.")

def sync_neo4j_lineage():
    print("\n🕸️ Phase 2: Neo4j Knowledge Graph Meta-Lineage Sync")
    print("----------------------------------------------------")

    for schema, tbl_name, cube_name, kg_entity, desc in LINEAGE_MAP:
        cypher = f"""
        MERGE (t:PostgreSQLTable {{fqn: '{schema}.{tbl_name}'}})
        ON CREATE SET t.schema = '{schema}', t.name = '{tbl_name}'

        MERGE (c:SemanticCube {{name: '{cube_name}'}})
        ON CREATE SET c.engine = 'Cube.js', c.description = '{desc}'

        MERGE (k:KnowledgeEntityType {{name: '{kg_entity}'}})
        ON CREATE SET k.domain = 'BIAN/FIBO'

        MERGE (t)-[r1:DERIVES_SEMANTICS_TO {{type: 'SQL_COMPUTE'}}]->(c)
        MERGE (c)-[r2:INSTANTIATES_GRAPH {{type: 'ENTITY_MAPPING'}}]->(k);
        """
        run_cypher(cypher)
        print(f"  🕸️ Graph Lineage: (:PostgreSQLTable `{schema}.{tbl_name}`) ➔ (:SemanticCube `{cube_name}`) ➔ (:KnowledgeEntity `{kg_entity}`)")

    print("✅ Neo4j Meta-Lineage Sync Complete!")

def main():
    print("🚀 Starting End-to-End Lineage Sync across PostgreSQL, Cube.js, and Neo4j...")
    sync_openmetadata_lineage()
    sync_neo4j_lineage()

    api_post("apps/trigger/SearchIndexingApplication")
    print("\n✅ End-to-End Lineage Sync Successfully Executed!")

if __name__ == "__main__":
    main()
