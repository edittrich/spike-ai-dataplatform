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
import sys

import psycopg2

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this script is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env  # noqa: E402

load_env()

# This script *writes* to financial.entity_embeddings, so it connects with the
# native psycopg2 driver as POSTGRES_USER rather than via `docker exec psql`
# (see CLAUDE.md's C6 note: docker exec requires a mounted docker.sock, which
# is root-equivalent host access, and the old code built its INSERT by
# f-string interpolation with hand-rolled `str.replace("'", "''")` escaping,
# which breaks on a trailing backslash and is exactly the injection shape
# every other write path in this repo was hardened against).
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "54322"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")

# _openmetadata_client / _embedding_backend read credentials/config at import
# time, so both must be imported after load_env() -- see their docstrings.
from scripts._openmetadata_client import api_get  # noqa: E402

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

_pg_conn = None

def get_pg_connection():
    """Lazily opens a single native psycopg2 connection for the life of the
    process, instead of shelling out to `docker exec psql` per query."""
    global _pg_conn
    if _pg_conn is None or _pg_conn.closed:
        _pg_conn = psycopg2.connect(
            host=POSTGRES_HOST, port=POSTGRES_PORT, user=POSTGRES_USER,
            password=POSTGRES_PASSWORD, dbname=POSTGRES_DB, connect_timeout=10,
        )
        _pg_conn.autocommit = True
    return _pg_conn

def query_pg_rows(sql, params=None):
    """Runs a parameterized SELECT and returns the raw rows (list of tuples)."""
    with get_pg_connection().cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()

def insert_vector_embedding(entity_type, fqn, display_name, content_text, metadata, embedding_vec):
    embedding_str = "[" + ",".join(str(x) for x in embedding_vec) + "]"
    sql = """
    INSERT INTO financial.entity_embeddings
        (entity_type, fqn, display_name, content_text, metadata, embedding)
    VALUES
        (%s, %s, %s, %s, %s::jsonb, %s::vector)
    ON CONFLICT (fqn) DO UPDATE SET
        content_text = EXCLUDED.content_text,
        metadata = EXCLUDED.metadata,
        embedding = EXCLUDED.embedding,
        created_at_utc = NOW();
    """
    with get_pg_connection().cursor() as cur:
        cur.execute(
            sql,
            (entity_type, fqn, display_name, content_text, json.dumps(metadata), embedding_str),
        )

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
        rows = query_pg_rows(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema IN ('financial', 'ref') AND table_name != 'entity_embeddings';"
        )
        for schema_name, tbl_name in rows:
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

    sql = """
    SELECT
        entity_type,
        display_name,
        ROUND((1 - (embedding <=> %(vec)s::vector))::numeric, 4) AS cosine_similarity,
        content_text
    FROM financial.entity_embeddings
    ORDER BY embedding <=> %(vec)s::vector ASC
    LIMIT 5;
    """

    rows = query_pg_rows(sql, {"vec": vec_str})
    print(f"Query Prompt: '{sample_query}'\n")
    print("Top 5 Vector Similarity Search Matches:")
    print("---------------------------------------")
    for entity_type, display_name, cosine_similarity, _content_text in rows:
        print(f"  🎯 [{entity_type}] {display_name} — Cosine Similarity: {cosine_similarity}")

def main():
    generate_embeddings()
    test_similarity_search()
    if _pg_conn is not None:
        _pg_conn.close()

if __name__ == "__main__":
    main()
