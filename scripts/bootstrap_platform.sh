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

step "1/10  Starting PostgreSQL (Supabase CLI) and applying migrations"
npm run supabase:start

step "2/10  Generating synthetic BIAN/FIBO data (writes supabase/seed.sql)"
python3 scripts/generate_synthetic_data.py

step "3/10  Loading seed data into PostgreSQL (supabase db reset)"
npm run supabase:db:reset

step "4/10  Syncing the postgres superuser's password after the reset"
# Real bug, found live while building orchestration/definitions.py's Dagster
# asset graph: `supabase db reset` always resets the postgres role's TCP
# password back to the Supabase CLI's fixed local-dev default, silently
# overriding POSTGRES_PASSWORD in .env -- every step below that connects as
# the postgres superuser over a native psycopg2/TCP connection (not
# `docker exec ... psql`, which uses unaffected local trust auth) would
# otherwise fail authentication. See
# scripts/sync_postgres_superuser_password.py's module docstring for the
# full story. Idempotent -- safe even if nothing needs syncing.
python3 scripts/sync_postgres_superuser_password.py

step "5/10  Starting the Docker Compose stack (OpenMetadata, Neo4j, Cube.js, Prometheus, Grafana, OTel Collector + Tempo, MCP sidecar)"
docker compose up -d

step "6/11  Waiting for openmetadata_server to report healthy (this is the slowest starter)"
tries=0
until [ "$(docker inspect -f '{{.State.Health.Status}}' openmetadata_server 2>/dev/null || echo starting)" = "healthy" ]; do
    tries=$((tries + 1))
    if [ "$tries" -gt 60 ]; then
        fail "openmetadata_server did not become healthy in time. Check: docker compose logs openmetadata_server"
    fi
    sleep 5
done

step "7/11  Rotating the OpenMetadata ingestion-bot token if it's missing/expiring soon"
# H10 (hardening plan) residual gap, closed 2026-08-08: idempotent -- a
# no-op if OPENMETADATA_JWT_TOKEN in .env is still valid for >14 days, so
# this is safe to run on every bootstrap, not just the first one. Needs
# openmetadata_server up (just confirmed above) and OPENMETADATA_ADMIN_EMAIL/
# PASSWORD set in .env -- see .env.example's comment on those two vars.
python3 scripts/rotate_openmetadata_bot_token.py

step "8/11  Configuring the least-privilege mcp_readonly Postgres role"
python3 scripts/configure_readonly_role.py

step "9/11  Building the Neo4j knowledge graph from PostgreSQL"
# --yes: this script now confirms before its unconditional `MATCH (n) DETACH
# DELETE n` graph wipe (C6 in the hardening plan) -- safe and expected to
# skip non-interactively here, since bootstrap_platform.sh is meant to run
# unattended from an empty checkout, where there's no existing graph to lose.
python3 scripts/build_knowledge_graph.py --yes

step "10/11  Registering table metadata into OpenMetadata (required by the next 4 steps)"
python3 scripts/populate_openmetadata_tables.py

# These four are mutually independent -- each depends only on step 10 above,
# not on each other -- run sequentially here for simplicity and clearer
# failure output; feel free to background/parallelize them if pipeline
# runtime matters more than that (or use orchestration/definitions.py's
# Dagster asset graph, which does exactly that -- see orchestration/README.md).
python3 scripts/automate_openmetadata_pii_and_profiling.py
python3 scripts/ground_fibo_ontology_uris.py
python3 scripts/register_openmetadata_data_contracts.py
python3 scripts/execute_openmetadata_data_quality_tests.py
python3 scripts/sync_end_to_end_lineage.py

step "11/11  Generating and indexing vector embeddings (genuinely the last step -- reads catalog + FIBO tags + data products from the steps above)"
python3 scripts/generate_vector_embeddings.py

step "Done"
echo "Platform is bootstrapped. Try:"
echo "  python3 -m mcp_server.test_mcp_server"
echo "  python3 scripts/hybrid_rag_retriever.py"
echo "  streamlit run scripts/rag_explorer_dashboard.py"
