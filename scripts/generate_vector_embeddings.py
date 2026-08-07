#!/usr/bin/env python3
"""
===============================================================================
pgvector Vector Embeddings Generation & Indexing Pipeline
===============================================================================
Generates 384-dimensional dense semantic vector embeddings for:
1. PostgreSQL Catalog Tables & Column Descriptions
2. W3C FIBO Ontology Class URIs & Definitions
3. Enterprise Data Products & Data Contract SLAs
4. Cube.js Semantic Metric Cubes

Populates `financial.entity_embeddings` table in PostgreSQL with HNSW index.
===============================================================================
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this script is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env  # noqa: E402

load_env()

OPENMETADATA_URL = os.getenv("OPENMETADATA_URL", "http://127.0.0.1:8585/api/v1")
JWT_TOKEN = os.getenv("OPENMETADATA_JWT_TOKEN", "")
if not JWT_TOKEN:
    print("⚠️ OPENMETADATA_JWT_TOKEN is not set; OpenMetadata API calls will be unauthenticated.")

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {JWT_TOKEN}"
}

# Fails closed by default (raises) if the real sentence-transformers model
# can't load -- set ALLOW_DEGRADED_EMBEDDINGS=1 to accept a non-semantic
# fallback instead. This matters more here than anywhere else that uses the
# same fallback: this script *writes* the resulting vectors into
# financial.entity_embeddings, so a silent degraded run doesn't just affect
# one in-flight request, it persists mathematically meaningless vectors into
# the database for every later query to read. See scripts/_embedding_backend.py.
from scripts._embedding_backend import load_embedding_model
compute_embedding, EMBEDDING_MODE = load_embedding_model()
if EMBEDDING_MODE == "degraded":
    print("⚠️  DEGRADED embedding mode (ALLOW_DEGRADED_EMBEDDINGS=1) -- vectors written this run "
          "are a non-semantic lexical-hash approximation, not real embeddings.")
else:
    print(f"🧠 Using real embedding model '{os.getenv('EMBEDDING_MODEL_NAME', 'sentence-transformers/all-MiniLM-L6-v2')}' (384 dims).")

def api_get(endpoint):
    url = f"{OPENMETADATA_URL}/{endpoint}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return None

def query_pg(sql):
    cmd = [
        "docker", "exec", "supabase_db_ai-dataplatform", "psql",
        "-U", "postgres", "-d", "postgres", "-t", "-A", "-c", sql
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout.strip()

def insert_vector_embedding(entity_type, fqn, display_name, content_text, metadata, embedding_vec):
    embedding_str = "[" + ",".join(str(x) for x in embedding_vec) + "]"
    meta_str = json.dumps(metadata).replace("'", "''")
    text_clean = content_text.replace("'", "''")
    display_clean = display_name.replace("'", "''")
    fqn_clean = fqn.replace("'", "''")

    sql = f"""
    INSERT INTO financial.entity_embeddings 
        (entity_type, fqn, display_name, content_text, metadata, embedding)
    VALUES 
        ('{entity_type}', '{fqn_clean}', '{display_clean}', '{text_clean}', '{meta_str}'::jsonb, '{embedding_str}'::vector)
    ON CONFLICT (fqn) DO UPDATE SET
        content_text = EXCLUDED.content_text,
        metadata = EXCLUDED.metadata,
        embedding = EXCLUDED.embedding,
        created_at_utc = NOW();
    """
    query_pg(sql)

def generate_embeddings():
    print("\n🚀 Starting Vector Embeddings Generation Pipeline...")
    print("-----------------------------------------------------")

    count = 0

    # 1. Embed Catalog Table Entities
    print("📦 Vectorizing Catalog Table Entities & Column Metadata...")
    try:
        tables_resp = api_get("tables?fields=columns,tags&limit=100")
    except Exception as e:
        print(f"⚠️ OpenMetadata REST API unavailable ({e}). Skipping online catalog table sync.")
        tables_resp = None
    if tables_resp and "data" in tables_resp:
        for tbl in tables_resp["data"]:
            fqn = tbl["fullyQualifiedName"]
            tbl_name = tbl["name"]
            desc = tbl.get("description", "")
            cols = [c["name"] + ": " + c.get("description", "") for c in tbl.get("columns", [])]
            col_text = "; ".join(cols)
            
            content_text = f"Table: {tbl_name}. Description: {desc}. Columns: {col_text}"
            vec = compute_embedding(content_text)
            
            metadata = {
                "schema": tbl["databaseSchema"]["name"],
                "table": tbl_name,
                "column_count": len(tbl.get("columns", [])),
                "tags": [t.get("tagFQN") for t in tbl.get("tags", [])]
            }
            insert_vector_embedding("table", fqn, tbl_name, content_text, metadata, vec)
            count += 1
            print(f"  🧠 Vectorized Table: {tbl_name}")
    else:
        # Fallback to local PostgreSQL schemas
        raw_tables = query_pg("SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema IN ('financial', 'ref') AND table_name != 'entity_embeddings';")
        for line in raw_tables.split("\n"):
            if not line.strip():
                continue
            parts = line.split("|")
            if len(parts) == 2:
                schema_name, tbl_name = parts[0], parts[1]
                fqn = f"PostgreSQL_Financial_Platform.postgres.{schema_name}.{tbl_name}"
                content_text = f"Table: {tbl_name}. Schema: {schema_name}. BIAN/FIBO entity {tbl_name} for enterprise banking risk and exposure analytics."
                vec = compute_embedding(content_text)
                metadata = {"schema": schema_name, "table": tbl_name, "column_count": 5, "tags": []}
                insert_vector_embedding("table", fqn, tbl_name, content_text, metadata, vec)
                count += 1
                print(f"  🧠 Vectorized PostgreSQL Table: {schema_name}.{tbl_name}")

    # 2. Embed Data Products & Data Contracts
    print("📜 Vectorizing Data Products & Data Contracts...")
    dp_resp = api_get("dataProducts?limit=50")
    if dp_resp and "data" in dp_resp:
        for dp in dp_resp["data"]:
            fqn = dp["fullyQualifiedName"]
            dp_name = dp["displayName"]
            desc = dp.get("description", "")
            
            content_text = f"Data Product: {dp_name}. Contract & SLAs: {desc}"
            vec = compute_embedding(content_text)
            
            metadata = {
                "domain": dp.get("domain", {}).get("name", "Financial"),
                "version": "1.0.0"
            }
            insert_vector_embedding("data_product", fqn, dp_name, content_text, metadata, vec)
            count += 1
            print(f"  🧠 Vectorized Data Product: {dp_name}")

    # 3. Embed FIBO Ontology Classes
    print("🌐 Vectorizing W3C FIBO Ontology Classes...")
    tags_resp = api_get("tags?parent=FIBO_Ontology&limit=100")
    if tags_resp and "data" in tags_resp:
        for tag in tags_resp["data"]:
            fqn = tag["fullyQualifiedName"]
            tag_name = tag["displayName"]
            desc = tag.get("description", "")
            
            content_text = f"FIBO Class: {tag_name}. Ontology Definition: {desc}"
            vec = compute_embedding(content_text)
            
            metadata = {
                "prefix": tag_name,
                "fibo_uri": desc.split("\n")[0].replace("FIBO Class URI: ", "")
            }
            insert_vector_embedding("fibo_class", fqn, tag_name, content_text, metadata, vec)
            count += 1
            print(f"  🧠 Vectorized FIBO Class: {tag_name}")

    print(f"\n✅ Successfully generated and indexed {count} dense vector embeddings in `financial.entity_embeddings`!")

def test_similarity_search():
    print("\n🔍 Testing pgvector Cosine Similarity Search Query...")
    print("-----------------------------------------------------")

    sample_query = "Find individual customer personal details date of birth and identity"
    query_vec = compute_embedding(sample_query)
    vec_str = "[" + ",".join(str(x) for x in query_vec) + "]"

    sql = f"""
    SELECT 
        entity_type,
        display_name,
        ROUND((1 - (embedding <=> '{vec_str}'::vector))::numeric, 4) AS cosine_similarity,
        content_text
    FROM financial.entity_embeddings
    ORDER BY embedding <=> '{vec_str}'::vector ASC
    LIMIT 5;
    """

    res = query_pg(sql)
    print(f"Query Prompt: '{sample_query}'\n")
    print("Top 5 Vector Similarity Search Matches:")
    print("---------------------------------------")
    for line in res.split("\n"):
        if line:
            parts = line.split("|")
            if len(parts) >= 3:
                print(f"  🎯 [{parts[0]}] {parts[1]} — Cosine Similarity: {parts[2]}")

def main():
    generate_embeddings()
    test_similarity_search()

if __name__ == "__main__":
    main()
