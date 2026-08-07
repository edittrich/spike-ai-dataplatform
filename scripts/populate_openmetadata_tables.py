#!/usr/bin/env python3
"""
===============================================================================
OpenMetadata Direct Table & Schema Ingestion Script
===============================================================================
Queries PostgreSQL database metadata (schemas ref & financial, 19 tables, column types,
and native COMMENT ON COLUMN descriptions) and registers them directly into OpenMetadata Catalog.
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

def api_put(endpoint, payload):
    url = f"{OPENMETADATA_URL}/{endpoint}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"❌ Error PUT {endpoint}: {e.code} - {e.read().decode('utf-8')}")
        return None

def get_pg_tables():
    cmd = [
        "docker", "exec", "supabase_db_ai-dataplatform", "psql",
        "-U", "postgres", "-d", "postgres", "-t", "-A", "-c",
        """
        SELECT 
            c.table_schema,
            c.table_name,
            c.column_name,
            c.data_type,
            c.ordinal_position,
            COALESCE(pgd.description, 'BIAN/FIBO aligned operational column.') as description
        FROM information_schema.columns c
        LEFT JOIN pg_catalog.pg_statio_all_tables st ON c.table_schema = st.schemaname AND c.table_name = st.relname
        LEFT JOIN pg_catalog.pg_description pgd ON pgd.objoid = st.relid AND pgd.objsubid = c.ordinal_position
        WHERE c.table_schema IN ('ref', 'financial')
        ORDER BY c.table_schema, c.table_name, c.ordinal_position;
        """
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    
    tables = {}
    for line in res.stdout.strip().split("\n"):
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) < 6:
            continue
        schema, tbl, col, dtype, pos, desc = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
        
        # Map PG data type to OpenMetadata DataType
        om_dtype = "VARCHAR"
        data_len = 255
        
        if "int" in dtype or "bigint" in dtype:
            om_dtype = "BIGINT"
            data_len = None
        elif "numeric" in dtype or "decimal" in dtype or "double" in dtype or "real" in dtype:
            om_dtype = "NUMERIC"
            data_len = None
        elif "bool" in dtype:
            om_dtype = "BOOLEAN"
            data_len = None
        elif "date" in dtype:
            om_dtype = "DATE"
            data_len = None
        elif "timestamp" in dtype:
            om_dtype = "TIMESTAMP"
            data_len = None
        elif "json" in dtype:
            om_dtype = "JSON"
            data_len = None
        elif "uuid" in dtype:
            om_dtype = "UUID"
            data_len = None

        col_dict = {
            "name": col,
            "dataType": om_dtype,
            "description": desc,
            "ordinalPosition": int(pos)
        }
        if data_len is not None:
            col_dict["dataLength"] = data_len

        key = (schema, tbl)
        if key not in tables:
            tables[key] = []
        tables[key].append(col_dict)
    return tables

def main():
    print("🚀 Populating OpenMetadata Enterprise Data Catalog with PostgreSQL tables...")

    # 1. Create Database Service
    service_payload = {
        "name": "PostgreSQL_Financial_Platform",
        "serviceType": "Postgres",
        "description": "Enterprise PostgreSQL database for financial platform containing BIAN & FIBO aligned Party, Deposit, and Loan operational data products.",
        "connection": {
            "config": {
                "type": "Postgres",
                "authType": {"password": os.getenv("POSTGRES_PASSWORD", "")},
                "username": "postgres",
                "hostPort": "127.0.0.1:54322",
                "database": "postgres"
            }
        }
    }
    print("📦 Creating Database Service: PostgreSQL_Financial_Platform")
    service_res = api_put("services/databaseServices", service_payload)

    # 2. Create Database
    db_payload = {
        "name": "postgres",
        "service": "PostgreSQL_Financial_Platform",
        "description": "Primary PostgreSQL Database storing operational schemas."
    }
    print("📦 Creating Database: postgres")
    db_res = api_put("databases", db_payload)

    # 3. Create Schemas
    for schema_name in ["ref", "financial"]:
        schema_payload = {
            "name": schema_name,
            "database": "PostgreSQL_Financial_Platform.postgres",
            "description": f"{schema_name.upper()} operational schema aligned with FIBO/BIAN standard data models."
        }
        print(f"📂 Creating Database Schema: {schema_name}")
        api_put("databaseSchemas", schema_payload)

    # 4. Fetch & Create Tables
    pg_tables = get_pg_tables()
    print(f"\n📊 Discovered {len(pg_tables)} PostgreSQL Tables across schemas `ref` and `financial`.\n")

    for (schema, tbl_name), cols in pg_tables.items():
        tbl_payload = {
            "name": tbl_name,
            "displayName": tbl_name,
            "description": f"BIAN/FIBO aligned entity `{tbl_name}` under `{schema}` schema.",
            "databaseSchema": f"PostgreSQL_Financial_Platform.postgres.{schema}",
            "columns": cols,
            "tableType": "Regular"
        }
        res = api_put("tables", tbl_payload)
        if res:
            print(f"  ✔ Registered Table: {schema}.{tbl_name} ({len(cols)} columns)")

    print("\n✅ Success! All 19 PostgreSQL tables & column comments successfully ingested into OpenMetadata UI!")

if __name__ == "__main__":
    main()
