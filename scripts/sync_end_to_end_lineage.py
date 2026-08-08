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

import re
import sys
import os

import yaml

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this script is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env  # noqa: E402

load_env()

# _neo4j_conn / _openmetadata_client read credentials at import time, so both
# must be imported *after* load_env() has populated the environment from
# .env -- importing them earlier silently captures empty credentials.
from scripts._neo4j_conn import get_driver  # noqa: E402
from scripts._openmetadata_client import api_get, api_put, api_post  # noqa: E402

# D4 (hardening plan): this used to register a `Cube_*` OpenMetadata entity
# per table with two invented columns (`measure_count` BIGINT, `dimension_id`
# UUID) matching nothing in cube/model/cubes/*.yml, and only table-level
# lineage edges. Fixed to parse the real cube definitions -- same source of
# truth Cube.js itself loads -- and to emit real columnsLineage
# (table.column -> cube.measure/dimension) wherever a measure/dimension's
# `sql:` is a bare column reference resolvable to a source column, not a
# cross-cube join or a computed expression.
CUBES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cube", "model", "cubes")

# Bare-identifier sql: values only (e.g. "principal_amount") -- deliberately
# excludes cross-cube references ("{deposit_balance.available_balance}"),
# computed expressions ("interest_rate * 100.0"), and measure-of-measure
# ratios ("100.0 * {npl_default_count} / NULLIF(...)"). Those establish real
# lineage too but from a different source column or no single source column
# at all -- out of scope for this pass; a bare match is unambiguous today and
# covers the majority of dimensions and simple sum/avg measures.
_BARE_COLUMN_SQL_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

_DIMENSION_TYPE_TO_OM_DTYPE = {
    "string": "VARCHAR",
    "number": "DOUBLE",
    "boolean": "BOOLEAN",
    "time": "TIMESTAMP",
}
_MEASURE_TYPE_TO_OM_DTYPE = {
    "count": "BIGINT",
    "countDistinct": "BIGINT",
    "sum": "DOUBLE",
    "avg": "DOUBLE",
    "number": "DOUBLE",
}


def load_cube_definition(tbl_name):
    """Parses cube/model/cubes/{tbl_name}.yml and returns its single cube dict,
    or None if the file doesn't exist (e.g. a table with no cube -- see D9)."""
    path = os.path.join(CUBES_DIR, f"{tbl_name}.yml")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        parsed = yaml.safe_load(f)
    cubes = parsed.get("cubes") or []
    return cubes[0] if cubes else None


def build_cube_columns_and_lineage(cube_def, pg_fqn, om_table_name):
    """Returns (om_columns, columns_lineage) for a real Cube.js cube definition.
    om_columns: OpenMetadata `columns` list for the Cube_* table entity.
    columns_lineage: list of {"fromColumns": [<source column FQN>], "toColumn": <cube column FQN>}
    for every dimension/measure whose `sql:` is a bare source-table column.

    om_table_name is the *registered OpenMetadata table entity name*
    (e.g. "Cube_Party") -- deliberately not cube_def["name"] (the Cube.js-
    internal name, e.g. "party"): a real bug caught live, the FQN built from
    the latter 400'd with "Invalid fully qualified column name" because it
    didn't match any entity OpenMetadata actually has registered."""
    om_columns = []
    columns_lineage = []

    for dim in cube_def.get("dimensions", []):
        om_dtype = _DIMENSION_TYPE_TO_OM_DTYPE.get(dim.get("type"), "VARCHAR")
        om_column = {
            "name": dim["name"],
            "dataType": om_dtype,
            "description": dim.get("title") or dim.get("description") or f"Cube.js dimension `{dim['name']}`.",
        }
        if om_dtype == "VARCHAR":
            # OpenMetadata rejects char/varchar/binary/varbinary columns with
            # no dataLength (verified live: PUT tables 400s otherwise) --
            # same 255 default populate_openmetadata_tables.py uses for the
            # real source tables' own VARCHAR columns.
            om_column["dataLength"] = 255
        om_columns.append(om_column)
        sql = str(dim.get("sql", "")).strip()
        if _BARE_COLUMN_SQL_RE.match(sql):
            columns_lineage.append({
                "fromColumns": [f"{pg_fqn}.{sql}"],
                "toColumn": f"Cube_Semantic_Engine.semantic_layer.cubes.{om_table_name}.{dim['name']}",
            })

    for measure in cube_def.get("measures", []):
        om_dtype = _MEASURE_TYPE_TO_OM_DTYPE.get(measure.get("type"), "DOUBLE")
        om_columns.append({
            "name": measure["name"],
            "dataType": om_dtype,
            "description": measure.get("title") or measure.get("description") or f"Cube.js measure `{measure['name']}`.",
        })
        sql = str(measure.get("sql", "")).strip()
        if _BARE_COLUMN_SQL_RE.match(sql):
            columns_lineage.append({
                "fromColumns": [f"{pg_fqn}.{sql}"],
                "toColumn": f"Cube_Semantic_Engine.semantic_layer.cubes.{om_table_name}.{measure['name']}",
            })

    if not om_columns:
        # Every real cube in this repo has at least one measure -- an empty
        # result means the YAML was malformed/unreadable, not a legitimately
        # column-less cube. Fail loudly rather than register a schema-less
        # table entity that silently carries no lineage at all.
        raise ValueError(f"Cube '{om_table_name}' parsed with zero measures/dimensions -- check its YAML.")

    return om_columns, columns_lineage

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

def sync_openmetadata_lineage() -> None:
    """Registers a Cube_* table entity (real measures/dimensions parsed from
    cube/model/cubes/*.yml, see build_cube_columns_and_lineage above) for
    every table in LINEAGE_MAP, then creates a table-level lineage edge from
    the real PostgreSQL table to it -- with columnsLineage wherever a
    measure/dimension resolves to a bare source column (D4)."""
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
    cube_columns_lineage_map = {}
    skipped_cubes = []
    for schema, tbl_name, cube_name, kg_entity, desc in LINEAGE_MAP:
        pg_fqn = f"PostgreSQL_Financial_Platform.postgres.{schema}.{tbl_name}"
        cube_def = load_cube_definition(tbl_name)
        if cube_def is None:
            # D9's ref.* cubes previously didn't exist at all -- now they do
            # (cube/model/cubes/ref_country.yml etc.), so this branch should
            # be unreachable for every entry in LINEAGE_MAP today. Kept as a
            # loud skip rather than a silent one in case LINEAGE_MAP is ever
            # extended ahead of the corresponding cube file being written.
            skipped_cubes.append(tbl_name)
            print(f"  ⚠️  No cube/model/cubes/{tbl_name}.yml found -- skipping {cube_name} (no fabricated placeholder registered).")
            continue

        om_columns, columns_lineage = build_cube_columns_and_lineage(cube_def, pg_fqn, cube_name)
        cube_payload = {
            "name": cube_name,
            "displayName": f"Cube.{cube_def['name']}",
            "description": cube_def.get("description") or f"Cube.js Semantic Cube for {desc}",
            "databaseSchema": "Cube_Semantic_Engine.semantic_layer.cubes",
            "columns": om_columns,
            "tableType": "View"
        }
        res = api_put("tables", cube_payload)
        if res and "id" in res:
            cube_id_map[cube_name] = res["id"]
            cube_columns_lineage_map[cube_name] = columns_lineage

    # Create Lineage Edges (PostgreSQL Table -> Cube.js Cube), now with
    # columnsLineage wherever a measure/dimension resolves to a bare source
    # column (see build_cube_columns_and_lineage) -- previously table-level
    # only, per D4.
    edge_count = 0
    column_edge_count = 0
    for schema, tbl_name, cube_name, kg_entity, desc in LINEAGE_MAP:
        if cube_name not in cube_id_map:
            continue
        pg_fqn = f"PostgreSQL_Financial_Platform.postgres.{schema}.{tbl_name}"
        from_id = table_id_map.get(pg_fqn)
        to_id = cube_id_map.get(cube_name)

        if from_id and to_id:
            columns_lineage = cube_columns_lineage_map.get(cube_name, [])
            lineage_details = {
                "description": f"Derives semantic metrics from physical table `{schema}.{tbl_name}` into `{cube_name}`"
            }
            if columns_lineage:
                lineage_details["columnsLineage"] = columns_lineage
            lineage_payload = {
                "edge": {
                    "fromEntity": {"id": from_id, "type": "table"},
                    "toEntity": {"id": to_id, "type": "table"},
                    "lineageDetails": lineage_details,
                }
            }
            res = api_put("lineage", lineage_payload)
            if res:
                edge_count += 1
                column_edge_count += len(columns_lineage)
                print(f"  🔗 Connected Lineage: {schema}.{tbl_name} ➔ Cube.{cube_name} ({len(columns_lineage)} column-level edges)")

    print(f"✅ OpenMetadata Lineage Sync Complete: Created {edge_count} table-level lineage edges "
          f"({column_edge_count} column-level edges within them); {len(skipped_cubes)} tables skipped (no cube definition).")

def sync_neo4j_lineage() -> None:
    """Mirrors LINEAGE_MAP into Neo4j as its own meta-lineage graph:
    (:PostgreSQLTable)-[:DERIVES_SEMANTICS_TO]->(:SemanticCube)-[:INSTANTIATES_GRAPH]->(:KnowledgeEntityType),
    separate from (and describing) the actual instance-data graph
    build_knowledge_graph.py builds."""
    print("\n🕸️ Phase 2: Neo4j Knowledge Graph Meta-Lineage Sync")
    print("----------------------------------------------------")

    cypher = """
    MERGE (t:PostgreSQLTable {fqn: $fqn})
    ON CREATE SET t.schema = $schema, t.name = $tbl_name

    MERGE (c:SemanticCube {name: $cube_name})
    ON CREATE SET c.engine = 'Cube.js', c.description = $desc

    MERGE (k:KnowledgeEntityType {name: $kg_entity})
    ON CREATE SET k.domain = 'BIAN/FIBO'

    MERGE (t)-[r1:DERIVES_SEMANTICS_TO {type: 'SQL_COMPUTE'}]->(c)
    MERGE (c)-[r2:INSTANTIATES_GRAPH {type: 'ENTITY_MAPPING'}]->(k);
    """
    driver = get_driver()
    try:
        with driver.session() as session:
            for schema, tbl_name, cube_name, kg_entity, desc in LINEAGE_MAP:
                session.run(cypher, {
                    "fqn": f"{schema}.{tbl_name}", "schema": schema, "tbl_name": tbl_name,
                    "cube_name": cube_name, "desc": desc, "kg_entity": kg_entity,
                }).consume()
                print(f"  🕸️ Graph Lineage: (:PostgreSQLTable `{schema}.{tbl_name}`) ➔ (:SemanticCube `{cube_name}`) ➔ (:KnowledgeEntity `{kg_entity}`)")
    finally:
        driver.close()

    print("✅ Neo4j Meta-Lineage Sync Complete!")

def main() -> None:
    """Runs both lineage syncs (OpenMetadata catalog, then Neo4j
    meta-lineage) and triggers a reindex so both render immediately."""
    print("🚀 Starting End-to-End Lineage Sync across PostgreSQL, Cube.js, and Neo4j...")
    sync_openmetadata_lineage()
    sync_neo4j_lineage()

    api_post("apps/trigger/SearchIndexingApplication")
    print("\n✅ End-to-End Lineage Sync Successfully Executed!")

if __name__ == "__main__":
    main()
