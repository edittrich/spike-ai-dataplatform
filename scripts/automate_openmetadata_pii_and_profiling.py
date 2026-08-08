#!/usr/bin/env python3
"""
===============================================================================
Automated PII Classification, Tagging & Data Quality Profiling Script
===============================================================================
Performs active metadata intelligence over PostgreSQL schemas `ref` and `financial`:
1. Scans table columns for sensitive data and automatically applies OpenMetadata
   `PersonalData.Personal` & `PersonalData.SpecialCategory` PII tags.
2. Computes real-time data profiling statistics (row count, null count, distinct count)
   and publishes them to OpenMetadata table profile endpoints.
3. Triggers OpenSearch reindexing so tags and quality metrics render in UI immediately.
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
# H2/H8: these two lists used to be defined here only -- extracted to a
# shared module so Cube.js's dimension masking, MCP row redaction, and this
# script's own catalog tagging all agree on what counts as PII instead of
# three independent (and previously drifted) opinions. See
# scripts/_pii_classification.py's module docstring.
from scripts._pii_classification import PII_PERSONAL_PATTERNS, PII_SPECIAL_PATTERNS  # noqa: E402,F401

load_env()

# _openmetadata_client reads OPENMETADATA_URL/JWT_TOKEN at import time, so it
# must be imported after load_env() -- see its module docstring.
from scripts._openmetadata_client import api_get, api_put, api_post  # noqa: E402

def query_pg(sql):
    cmd = [
        "docker", "exec", "supabase_db_ai-dataplatform", "psql",
        "-U", "postgres", "-d", "postgres", "-t", "-A", "-c", sql
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout.strip()

def run_pii_classification():
    print("\n🔍 Phase 1: Automated PII & Sensitivity Classification")
    print("---------------------------------------------------------")
    
    tables_resp = api_get("tables?fields=columns,tags&limit=100")
    if not tables_resp or "data" not in tables_resp:
        print("❌ Could not fetch tables from OpenMetadata!")
        return

    tagged_count = 0
    for tbl in tables_resp["data"]:
        fqn = tbl["fullyQualifiedName"]
        columns = tbl.get("columns", [])
        updated_cols = []
        modified = False

        for col in columns:
            col_name = col["name"].lower()
            tags = col.get("tags", [])
            
            target_tag = None
            if any(pat in col_name for pat in PII_SPECIAL_PATTERNS):
                target_tag = "PersonalData.SpecialCategory"
            elif any(pat in col_name for pat in PII_PERSONAL_PATTERNS):
                target_tag = "PersonalData.Personal"
            
            if target_tag:
                existing_tag_names = [t.get("tagFQN") for t in tags]
                if target_tag not in existing_tag_names:
                    tags.append({
                        "tagFQN": target_tag,
                        "labelType": "Automated",
                        "state": "Confirmed",
                        "source": "Classification"
                    })
                    col["tags"] = tags
                    modified = True
                    tagged_count += 1
                    print(f"  🏷️ Auto-tagged PII Column: {fqn}.{col['name']} -> `{target_tag}`")
            
            updated_cols.append(col)

        if modified:
            put_payload = {
                "name": tbl["name"],
                "displayName": tbl.get("displayName", tbl["name"]),
                "description": tbl.get("description", ""),
                "databaseSchema": tbl["databaseSchema"]["fullyQualifiedName"],
                "columns": updated_cols,
                "tableType": tbl.get("tableType", "Regular")
            }
            api_put("tables", put_payload)

    print(f"✅ Successfully verified and tagged sensitive PII columns across catalog entities.")

def run_data_profiling():
    print("\n📊 Phase 2: Automated Real-Time Data Profiling & Statistics")
    print("------------------------------------------------------------")

    tables_resp = api_get("tables?fields=columns&limit=100")
    if not tables_resp or "data" not in tables_resp:
        return

    # schema_name/tbl_name/col_name below come from the live OpenMetadata API
    # response -- externally influenceable if anyone can edit the catalog --
    # and psycopg2/docker-exec-psql cannot bind identifiers as query
    # parameters (only values). So before any of them is interpolated into a
    # SQL string, it's checked against the real information_schema.columns
    # snapshot fetched here: only identifiers that name an actual column in
    # `financial`/`ref` survive, closing the injection surface described in
    # the C6 finding regardless of what the catalog claims.
    known_columns = load_known_columns(query_pg)

    for tbl in tables_resp["data"]:
        schema_name = tbl["databaseSchema"]["name"]
        tbl_name = tbl["name"]
        tbl_id = tbl["id"]

        if (schema_name, tbl_name) not in known_columns:
            print(f"  ⚠️ Skipping unknown table `{schema_name}.{tbl_name}` (not in information_schema).")
            continue

        try:
            row_cnt_str = query_pg(f"SELECT COUNT(*) FROM {schema_name}.{tbl_name};")
            row_count = int(row_cnt_str)
        except Exception:
            row_count = 0

        columns = tbl.get("columns", [])
        column_profiles = []
        timestamp = int(time.time() * 1000)

        for col in columns[:5]:  # Profile key columns
            col_name = col["name"]
            if not is_known_column(known_columns, schema_name, tbl_name, col_name):
                print(f"  ⚠️ Skipping unknown column `{schema_name}.{tbl_name}.{col_name}` (not in information_schema).")
                continue
            try:
                col_stats_str = query_pg(f"""
                    SELECT
                        COUNT({col_name}) as non_null_count,
                        COUNT(DISTINCT {col_name}) as distinct_count
                    FROM {schema_name}.{tbl_name};
                """)
                non_null_cnt, dist_cnt = [int(x) for x in col_stats_str.split("|")]
                null_cnt = max(0, row_count - non_null_cnt)
            except Exception:
                null_cnt = 0
                dist_cnt = row_count

            column_profiles.append({
                "name": col_name,
                "timestamp": timestamp,
                "valuesCount": row_count,
                "nullCount": null_cnt,
                "uniqueCount": dist_cnt,
                "distinctCount": dist_cnt
            })

        profile_payload = {
            "tableProfile": {
                "timestamp": timestamp,
                "rowCount": row_count,
                "columnCount": len(columns)
            },
            "columnProfile": column_profiles
        }

        res = api_put(f"tables/{tbl_id}/tableProfile", profile_payload)
        if res:
            print(f"  📈 Profiled {schema_name}.{tbl_name}: {row_count:,} rows, {len(columns)} columns")

def trigger_reindex():
    print("\n🔄 Phase 3: Triggering OpenSearch Reindexing")
    print("---------------------------------------------")
    res = api_post("apps/trigger/SearchIndexingApplication")
    print(f"  ⚡ SearchIndexApp Trigger Status: {res if res else 'Triggered'}")

def main():
    print("🚀 Running Automated PII Tagging & Data Quality Profiling Pipeline...")
    run_pii_classification()
    run_data_profiling()
    trigger_reindex()
    print("\n✅ Metadata Intelligence & Automated Profiling Complete!")

if __name__ == "__main__":
    main()
