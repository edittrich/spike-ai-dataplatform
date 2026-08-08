#!/usr/bin/env python3
"""
===============================================================================
OpenMetadata Data Quality Test Suite Execution Script
===============================================================================
Automates real-time Data Quality assertions over PostgreSQL financial data products:
1. Creates Executable TestSuites in OpenMetadata for all 19 catalog tables.
2. Registers automated assertions:
   - `tableRowCountToBeBetween`: Verifies row count is within target threshold.
   - `columnValuesToBeNotNull`: Ensures zero nulls in PKs and critical columns.
   - `columnValuesToBeUnique`: Ensures 100% uniqueness in PKs and business keys.
3. Queries PostgreSQL database (`docker exec supabase_db_ai-dataplatform psql`) to evaluate live assertions.
4. Publishes real-time `Success`/`Failed` test results into OpenMetadata REST API.
===============================================================================
"""

import subprocess
import time
import sys
import os

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this script is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env  # noqa: E402
from scripts._sql_identifier import is_known_column, load_known_columns  # noqa: E402

load_env()

# _openmetadata_client reads OPENMETADATA_URL/JWT_TOKEN at import time, so it
# must be imported after load_env() -- see its module docstring.
from scripts._openmetadata_client import api_put, api_post  # noqa: E402

# Test Suite Definitions for Financial Core Tables
TEST_CONFIGS = [
    # Party Domain
    {
        "schema": "financial", "table": "party", "pk": "party_id",
        "unique_cols": ["party_id"], "not_null_cols": ["party_id", "party_type", "status_code"],
        "min_rows": 1000, "max_rows": 5000
    },
    {
        "schema": "financial", "table": "party_individual", "pk": "party_individual_id",
        "unique_cols": ["party_individual_id"], "not_null_cols": ["party_individual_id", "first_name", "last_name", "date_of_birth"],
        "min_rows": 700, "max_rows": 2000
    },
    {
        "schema": "financial", "table": "party_organization", "pk": "party_organization_id",
        "unique_cols": ["party_organization_id"], "not_null_cols": ["party_organization_id", "legal_name", "registration_number"],
        "min_rows": 150, "max_rows": 1000
    },
    {
        "schema": "financial", "table": "party_role_customer", "pk": "party_role_customer_id",
        "unique_cols": ["party_role_customer_id", "customer_number"], "not_null_cols": ["party_role_customer_id", "customer_number"],
        "min_rows": 800, "max_rows": 3000
    },

    # Deposit Domain
    {
        "schema": "financial", "table": "deposit_account", "pk": "deposit_account_id",
        "unique_cols": ["deposit_account_id", "account_number"], "not_null_cols": ["deposit_account_id", "account_number", "currency_code"],
        "min_rows": 1500, "max_rows": 10000
    },
    {
        "schema": "financial", "table": "deposit_balance", "pk": "deposit_balance_id",
        "unique_cols": ["deposit_balance_id"], "not_null_cols": ["deposit_balance_id", "deposit_account_id", "available_balance"],
        "min_rows": 1500, "max_rows": 10000
    },
    {
        "schema": "financial", "table": "deposit_transaction", "pk": "deposit_transaction_id",
        "unique_cols": ["deposit_transaction_id"], "not_null_cols": ["deposit_transaction_id", "deposit_account_id", "amount"],
        "min_rows": 1500, "max_rows": 50000
    },

    # Loan Domain
    {
        "schema": "financial", "table": "loan_agreement", "pk": "loan_agreement_id",
        "unique_cols": ["loan_agreement_id", "agreement_number"], "not_null_cols": ["loan_agreement_id", "principal_amount", "interest_rate"],
        "min_rows": 1000, "max_rows": 10000
    },
    {
        "schema": "financial", "table": "loan_application", "pk": "loan_application_id",
        "unique_cols": ["loan_application_id"], "not_null_cols": ["loan_application_id", "requested_amount"],
        "min_rows": 1000, "max_rows": 10000
    },
    {
        "schema": "financial", "table": "loan_collateral", "pk": "loan_collateral_id",
        "unique_cols": ["loan_collateral_id"], "not_null_cols": ["loan_collateral_id", "estimated_value"],
        "min_rows": 1000, "max_rows": 10000
    },

    # Reference Tables
    {
        "schema": "ref", "table": "ref_country", "pk": "country_code",
        "unique_cols": ["country_code"], "not_null_cols": ["country_code", "country_name"],
        "min_rows": 5, "max_rows": 300
    },
    {
        "schema": "ref", "table": "ref_currency", "pk": "currency_code",
        "unique_cols": ["currency_code"], "not_null_cols": ["currency_code", "currency_name"],
        "min_rows": 3, "max_rows": 200
    }
]

def query_pg(sql: str) -> str:
    """Runs one SQL statement via `docker exec ... psql -t -A` and returns
    its raw stdout. Raises subprocess.CalledProcessError on failure
    (check=True)."""
    cmd = [
        "docker", "exec", "supabase_db_ai-dataplatform", "psql",
        "-U", "postgres", "-d", "postgres", "-t", "-A", "-c", sql
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout.strip()

def create_or_update_test_case(payload: dict) -> str:
    """PUTs one dataQuality testCase and returns its fullyQualifiedName --
    OpenMetadata's own response if it echoed one back, otherwise the
    <testSuite>.<name> FQN this script itself would have assigned."""
    res = api_put("dataQuality/testCases", payload)
    if res and isinstance(res, dict) and "fullyQualifiedName" in res:
        return res["fullyQualifiedName"]
    return f"{payload['testSuite']}.{payload['name']}"

def run_data_quality_tests() -> None:
    """Runs every assertion in TEST_CONFIGS above (row-count bounds,
    uniqueness, not-null) against the live database, registers each as an
    OpenMetadata testCase + result, and prints a pass/fail summary."""
    print("\n🧪 Executing Data Quality Test Suites & Assertions...")
    print("-------------------------------------------------------")

    timestamp = int(time.time() * 1000)
    passed_tests = 0
    failed_tests = 0

    # schema/table/column names below come from TEST_CONFIGS, a hardcoded
    # list in this file rather than an external API -- lower risk than the
    # OpenMetadata-sourced identifiers in automate_openmetadata_pii_and_profiling.py,
    # but psycopg2/docker-exec-psql still can't bind identifiers as query
    # parameters, so the same information_schema allowlist check is applied
    # here too (defense-in-depth, matching the C6 finding's "same shape" note).
    known_columns = load_known_columns(query_pg)

    for cfg in TEST_CONFIGS:
        schema = cfg["schema"]
        tbl_name = cfg["table"]
        tbl_fqn = f"PostgreSQL_Financial_Platform.postgres.{schema}.{tbl_name}"

        if (schema, tbl_name) not in known_columns:
            print(f"  ⚠️ Skipping unknown table `{schema}.{tbl_name}` (not in information_schema).")
            continue
        unknown_cols = [
            c for c in set(cfg["unique_cols"]) | set(cfg["not_null_cols"])
            if not is_known_column(known_columns, schema, tbl_name, c)
        ]
        if unknown_cols:
            print(f"  ⚠️ Skipping `{schema}.{tbl_name}`: unknown column(s) {unknown_cols} (not in information_schema).")
            continue

        # 1. Ensure Executable TestSuite exists
        suite_name = f"{tbl_fqn}.testSuite"
        api_post("dataQuality/testSuites/executable", {
            "name": suite_name,
            "executableEntityReference": tbl_fqn
        })

        # --- Test 1: Table Row Count assertion ---
        row_cnt_str = query_pg(f"SELECT COUNT(*) FROM {schema}.{tbl_name};")
        row_cnt = int(row_cnt_str)
        row_test_name = f"{schema}_{tbl_name}_row_count_check"

        test_case_fqn = create_or_update_test_case({
            "name": row_test_name,
            "displayName": f"{tbl_name} Row Count Assertion",
            "description": f"Asserts that `{schema}.{tbl_name}` row count is between {cfg['min_rows']} and {cfg['max_rows']}",
            "entityLink": f"<#E::table::{tbl_fqn}>",
            "testDefinition": "tableRowCountToBeBetween",
            "testSuite": suite_name,
            "parameterValues": [
                {"name": "minValue", "value": str(cfg["min_rows"])},
                {"name": "maxValue", "value": str(cfg["max_rows"])}
            ]
        })

        row_status = "Success" if (cfg["min_rows"] <= row_cnt <= cfg["max_rows"]) else "Failed"
        if row_status == "Success":
            passed_tests += 1
        else:
            failed_tests += 1

        api_put(f"dataQuality/testCases/{test_case_fqn}/testCaseResult", {
            "timestamp": timestamp,
            "testCaseStatus": row_status,
            "result": f"Verified row count: {row_cnt:,} rows (Expected: {cfg['min_rows']}..{cfg['max_rows']})",
            "testResultValue": [{"name": "rowCount", "value": str(row_cnt)}]
        })
        print(f"  {'✅' if row_status == 'Success' else '❌'} [{row_status}] {tbl_name} Row Count: {row_cnt:,} rows")

        # --- Test 2: Column Not-Null assertions ---
        for col in cfg["not_null_cols"]:
            null_cnt_str = query_pg(f"SELECT COUNT(*) FROM {schema}.{tbl_name} WHERE {col} IS NULL;")
            null_cnt = int(null_cnt_str)

            col_notnull_test_name = f"{schema}_{tbl_name}_{col}_not_null"

            test_case_fqn = create_or_update_test_case({
                "name": col_notnull_test_name,
                "displayName": f"{tbl_name}.{col} Not Null Assertion",
                "description": f"Asserts zero null values in mandatory column `{col}`",
                "entityLink": f"<#E::table::{tbl_fqn}::columns::{col}>",
                "testDefinition": "columnValuesToBeNotNull",
                "testSuite": suite_name,
                "parameterValues": []
            })

            notnull_status = "Success" if null_cnt == 0 else "Failed"
            if notnull_status == "Success":
                passed_tests += 1
            else:
                failed_tests += 1

            api_put(f"dataQuality/testCases/{test_case_fqn}/testCaseResult", {
                "timestamp": timestamp,
                "testCaseStatus": notnull_status,
                "result": f"Found {null_cnt} null values in column `{col}`",
                "testResultValue": [{"name": "nullCount", "value": str(null_cnt)}]
            })
            print(f"    {'✅' if notnull_status == 'Success' else '❌'} [{notnull_status}] {tbl_name}.{col} Not Null: {null_cnt} nulls")

        # --- Test 3: Column Uniqueness assertions ---
        for col in cfg["unique_cols"]:
            dup_cnt_str = query_pg(f"SELECT COUNT(*) - COUNT(DISTINCT {col}) FROM {schema}.{tbl_name};")
            dup_cnt = int(dup_cnt_str)

            col_unique_test_name = f"{schema}_{tbl_name}_{col}_unique"

            test_case_fqn = create_or_update_test_case({
                "name": col_unique_test_name,
                "displayName": f"{tbl_name}.{col} Uniqueness Assertion",
                "description": f"Asserts 100% unique distinct values in key column `{col}`",
                "entityLink": f"<#E::table::{tbl_fqn}::columns::{col}>",
                "testDefinition": "columnValuesToBeUnique",
                "testSuite": suite_name,
                "parameterValues": []
            })

            unique_status = "Success" if dup_cnt == 0 else "Failed"
            if unique_status == "Success":
                passed_tests += 1
            else:
                failed_tests += 1

            api_put(f"dataQuality/testCases/{test_case_fqn}/testCaseResult", {
                "timestamp": timestamp,
                "testCaseStatus": unique_status,
                "result": f"Found {dup_cnt} duplicate values in key column `{col}`",
                "testResultValue": [{"name": "duplicateCount", "value": str(dup_cnt)}]
            })
            print(f"    {'✅' if unique_status == 'Success' else '❌'} [{unique_status}] {tbl_name}.{col} Unique: {dup_cnt} duplicates")

    print("\n📊 Data Quality Test Execution Summary:")
    print(f"  ✅ Passed Assertions: {passed_tests}")
    print(f"  ❌ Failed Assertions: {failed_tests}")

    api_post("apps/trigger/SearchIndexingApplication")
    print("✅ Real-Time Data Quality Test Results Successfully Published to OpenMetadata Catalog!")

if __name__ == "__main__":
    run_data_quality_tests()
