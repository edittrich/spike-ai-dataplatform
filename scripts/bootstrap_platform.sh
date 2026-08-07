#!/usr/bin/env bash
# ===============================================================================
# Single-Entrypoint Platform Bootstrap
# ===============================================================================
# Runs the full path from an empty checkout to a queryable platform: starts
# PostgreSQL (Supabase CLI) and applies migrations, seeds synthetic data,
# starts the Docker Compose stack, configures the least-privilege database
# role, and runs the metadata/catalog pipeline in dependency order.
#
# This exists because CLAUDE.md's documented pipeline previously had two real
# gaps: `generate_synthetic_data.py` only writes supabase/seed.sql (nothing
# applied the schema or loaded it), and `populate_openmetadata_tables.py` --
# required by four later steps -- was missing from the documented order
# entirely. See docs/APPLICATION_RUNBOOK.md section 2 for the script-by-script
# rationale this encodes.
#
# Usage: ./scripts/bootstrap_platform.sh
# Safe to re-run: every step here is idempotent (migrations use IF NOT EXISTS/
# CREATE OR REPLACE-style guards, `supabase db reset` is a full reset by
# design, and the catalog scripts upsert rather than duplicate).
# ===============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
fail() { printf '\033[1;31mERROR:\033[0m %s\n' "$1" >&2; exit 1; }

[ -f .env ] || fail ".env not found. Run 'cp .env.example .env' and fill in the required values first."

step "1/9  Starting PostgreSQL (Supabase CLI) and applying migrations"
npm run supabase:start

step "2/9  Generating synthetic BIAN/FIBO data (writes supabase/seed.sql)"
python3 scripts/generate_synthetic_data.py

step "3/9  Loading seed data into PostgreSQL (supabase db reset)"
npm run supabase:db:reset

step "4/9  Starting the Docker Compose stack (OpenMetadata, Neo4j, Cube.js, Prometheus, Grafana, MCP sidecar)"
docker compose up -d

step "5/9  Waiting for openmetadata_server to report healthy (this is the slowest starter)"
tries=0
until [ "$(docker inspect -f '{{.State.Health.Status}}' openmetadata_server 2>/dev/null || echo starting)" = "healthy" ]; do
    tries=$((tries + 1))
    if [ "$tries" -gt 60 ]; then
        fail "openmetadata_server did not become healthy in time. Check: docker compose logs openmetadata_server"
    fi
    sleep 5
done

step "6/9  Configuring the least-privilege mcp_readonly Postgres role"
python3 scripts/configure_readonly_role.py

step "7/9  Building the Neo4j knowledge graph from PostgreSQL"
python3 scripts/build_knowledge_graph.py

step "8/9  Registering table metadata into OpenMetadata (required by the next 4 steps)"
python3 scripts/populate_openmetadata_tables.py

# These four are mutually independent -- each depends only on step 8 above,
# not on each other -- run sequentially here for simplicity and clearer
# failure output; feel free to background/parallelize them if pipeline
# runtime matters more than that.
python3 scripts/automate_openmetadata_pii_and_profiling.py
python3 scripts/ground_fibo_ontology_uris.py
python3 scripts/register_openmetadata_data_contracts.py
python3 scripts/execute_openmetadata_data_quality_tests.py
python3 scripts/sync_end_to_end_lineage.py

step "9/9  Generating and indexing vector embeddings (genuinely the last step -- reads catalog + FIBO tags + data products from the steps above)"
python3 scripts/generate_vector_embeddings.py

step "Done"
echo "Platform is bootstrapped. Try:"
echo "  python3 -m mcp_server.test_mcp_server"
echo "  python3 scripts/hybrid_rag_retriever.py"
echo "  streamlit run scripts/rag_explorer_dashboard.py"
