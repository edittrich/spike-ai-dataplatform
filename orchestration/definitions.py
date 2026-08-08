#!/usr/bin/env python3
"""
===============================================================================
Dagster Orchestration for the AI-Enabled Data Platform Pipeline
===============================================================================
Replaces the prose-only ordering previously documented in CLAUDE.md/README.md
(and encoded, imperatively, in scripts/bootstrap_platform.sh) with a real
Dagster asset graph -- Part 5 item 1 in the hardening plan: "the 8-step
pipeline is run by hand, ordering encoded only in prose; no retries,
backfill, or run history." Dagster's asset model maps directly onto this
platform's existing shape: each pipeline script already produces exactly one
externally-visible dataset (a Postgres load, a Neo4j graph, a set of
OpenMetadata entities, a pgvector index, ...), so each becomes one `@asset`
with `deps=[...]` expressing its *real* dependencies -- not the mostly-linear
order the scripts happen to be listed in.

Deliberately thin wrappers, not a rewrite: every asset shells out to the
existing, already-hardened script via subprocess (`python3 scripts/X.py`),
exactly the way a human or bootstrap_platform.sh already invokes it. Two
reasons this is the right call, not a shortcut:
  1. Several of these scripts call `sys.exit(1)` on a real failure condition
     (a missing required env var, a guardrail rejection, ...). Importing
     their `main()` and calling it in-process would let that `sys.exit(1)`
     kill Dagster's own long-lived webserver/daemon process, not just fail
     one run. A subprocess's exit code is just data to the parent process.
  2. It keeps one source of truth for the actual pipeline logic -- this file
     adds orchestration on top, it doesn't duplicate what generate_vector_embeddings.py
     etc. already do (and already have live-verified behavior for).

Scope boundary: this graph starts from `synthetic_seed_data` and ends at
`vector_embeddings` -- the same 8-ish data-producing steps CLAUDE.md's "Full
data pipeline" section documents. Starting PostgreSQL (Supabase CLI) and the
Docker Compose stack is a separate, explicit prerequisite (see
orchestration/README.md), not something an asset tries to manage -- Dagster
orchestrates data pipelines, it isn't a service/container manager, and
folding `docker compose up -d` into asset code would just reinvent
bootstrap_platform.sh's infra-startup half worse.
===============================================================================
"""

import subprocess
import sys
from pathlib import Path

from dagster import (
    AssetExecutionContext,
    Definitions,
    MaterializeResult,
    MetadataValue,
    RetryPolicy,
    ScheduleDefinition,
    asset,
    define_asset_job,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Applied to every asset that talks to a live service (Postgres/Neo4j/
# OpenMetadata/Cube.js) -- exactly the "no retries" gap this item's
# remediation named. Not applied to synthetic_seed_data, which is pure local
# file I/O with nothing transient to retry.
_SERVICE_RETRY_POLICY = RetryPolicy(max_retries=2, delay=10)


def _run_script(context: AssetExecutionContext, script: str, args: list[str] | None = None) -> MaterializeResult:
    """Runs `python3 scripts/<script> [args]` as a subprocess, streams its
    output into the Dagster run's own log (so `dagster dev`'s UI shows
    exactly what the script printed, not just pass/fail), and raises if it
    exits non-zero -- the same contract CI already relies on for these
    scripts (see .github/workflows/ci.yml)."""
    cmd = [sys.executable, f"scripts/{script}", *(args or [])]
    context.log.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.stdout:
        context.log.info(result.stdout)
    if result.stderr:
        context.log.info(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(
            f"scripts/{script} exited {result.returncode}. Last stderr lines:\n"
            + "\n".join(result.stderr.splitlines()[-20:])
        )
    tail = "\n".join(result.stdout.splitlines()[-15:]) or "(no stdout)"
    return MaterializeResult(metadata={"script": script, "exit_code": 0, "stdout_tail": MetadataValue.md(f"```\n{tail}\n```")})


def _run_npm(context: AssetExecutionContext, npm_script: str) -> MaterializeResult:
    cmd = ["npm", "run", npm_script]
    context.log.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.stdout:
        context.log.info(result.stdout)
    if result.stderr:
        context.log.info(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"npm run {npm_script} exited {result.returncode}: {result.stderr[-2000:]}")
    return MaterializeResult(metadata={"npm_script": npm_script, "exit_code": 0})


# ----------------------------------------------------------------------------
# A. Ingestion
# ----------------------------------------------------------------------------

@asset(group_name="ingestion", description="Writes supabase/seed.sql from the synthetic BIAN/FIBO generator. Pure local file I/O -- doesn't touch Postgres itself (see D1 in the hardening plan for why that surprised a past reader of this pipeline).")
def synthetic_seed_data(context: AssetExecutionContext) -> MaterializeResult:
    return _run_script(context, "generate_synthetic_data.py")


@asset(group_name="ingestion", deps=[synthetic_seed_data], retry_policy=_SERVICE_RETRY_POLICY,
       description="Applies supabase/migrations/*.sql and loads seed.sql via the Supabase CLI. Requires PostgreSQL already running (`npm run supabase:start`) -- external prerequisite, not an asset dependency Dagster manages.")
def postgres_seeded(context: AssetExecutionContext) -> MaterializeResult:
    return _run_npm(context, "supabase:db:reset")


@asset(group_name="ingestion", deps=[postgres_seeded], retry_policy=_SERVICE_RETRY_POLICY,
       description="Real bug, found live while building this asset graph: `supabase db reset` always resets the postgres role's password back to the Supabase CLI's fixed local-dev default, silently overriding POSTGRES_PASSWORD in .env -- every asset below that connects as the postgres superuser would otherwise fail authentication after every single reset. See scripts/sync_postgres_superuser_password.py's module docstring for the full story (including why it's supabase_admin, not postgres itself, that has to perform the fix).")
def postgres_superuser_synced(context: AssetExecutionContext) -> MaterializeResult:
    return _run_script(context, "sync_postgres_superuser_password.py")


@asset(group_name="ingestion", deps=[postgres_superuser_synced], retry_policy=_SERVICE_RETRY_POLICY,
       description="Sets the least-privilege mcp_readonly Postgres role's login password (idempotent). Nothing else in this pipeline depends on it -- only the MCP server / hybrid RAG retriever connect as this role, at query time, not during ingestion.")
def readonly_role_configured(context: AssetExecutionContext) -> MaterializeResult:
    return _run_script(context, "configure_readonly_role.py")


# ----------------------------------------------------------------------------
# B. Knowledge Graph
# ----------------------------------------------------------------------------

@asset(group_name="graph", deps=[postgres_seeded], retry_policy=_SERVICE_RETRY_POLICY,
       description="Loads PostgreSQL data into Neo4j. Wipes and rebuilds the graph on every run (--yes confirms this non-interactively -- see the C6 finding for why a confirmation exists at all) -- anything that also writes to Neo4j (lineage_dag below) must be ordered *after* this, not before, or its writes get wiped by the next rebuild. Depends only on postgres_seeded, not postgres_superuser_synced: its PostgreSQL reads go through `docker exec ... psql` (local trust auth inside the container, verified unaffected by the TCP password reset), not a native psycopg2/TCP connection.")
def knowledge_graph(context: AssetExecutionContext) -> MaterializeResult:
    return _run_script(context, "build_knowledge_graph.py", ["--yes"])


# ----------------------------------------------------------------------------
# C. Catalog & Governance
# ----------------------------------------------------------------------------

@asset(group_name="catalog", retry_policy=_SERVICE_RETRY_POLICY,
       description="H10 (hardening plan) residual gap, closed 2026-08-08: rotates OPENMETADATA_JWT_TOKEN in .env before it expires. Idempotent -- a no-op if the current token still has >14 days left, so materializing this on every pipeline run (or via bot_token_rotation_schedule below, independent of the pipeline) is cheap and safe. No deps of its own -- only needs openmetadata_server reachable, which docker compose's own depends_on/healthcheck already guarantee once the container is up; not gated on any other asset here.")
def bot_token_rotated(context: AssetExecutionContext) -> MaterializeResult:
    return _run_script(context, "rotate_openmetadata_bot_token.py")


@asset(group_name="catalog", deps=[postgres_seeded, bot_token_rotated], retry_policy=_SERVICE_RETRY_POLICY,
       description="Registers PostgreSQL tables into OpenMetadata. Required before every asset in this group below -- they all fetch table entities from the catalog and silently no-op if this hasn't run yet (see D1 in the hardening plan; this dependency used to be undocumented). Also depends on bot_token_rotated: every OpenMetadata write in this group authenticates as the ingestion-bot, so a stale/expired token here would fail every asset below, not just this one.")
def catalog_tables(context: AssetExecutionContext) -> MaterializeResult:
    return _run_script(context, "populate_openmetadata_tables.py")


@asset(group_name="catalog", deps=[catalog_tables], retry_policy=_SERVICE_RETRY_POLICY,
       description="PII tagging + statistical profiling over catalog tables.")
def pii_tags_and_profiles(context: AssetExecutionContext) -> MaterializeResult:
    return _run_script(context, "automate_openmetadata_pii_and_profiling.py")


@asset(group_name="catalog", deps=[catalog_tables], retry_policy=_SERVICE_RETRY_POLICY,
       description="Grounds catalog table entities to W3C FIBO ontology class URIs.")
def fibo_groundings(context: AssetExecutionContext) -> MaterializeResult:
    return _run_script(context, "ground_fibo_ontology_uris.py")


@asset(group_name="catalog", deps=[catalog_tables], retry_policy=_SERVICE_RETRY_POLICY,
       description="Publishes OpenMetadata Domains + ODCS-style Data Product contracts from contracts/*.yaml.")
def data_contracts(context: AssetExecutionContext) -> MaterializeResult:
    return _run_script(context, "register_openmetadata_data_contracts.py")


@asset(group_name="catalog", deps=[catalog_tables], retry_policy=_SERVICE_RETRY_POLICY,
       description="Registers and runs OpenMetadata data quality test assertions per table.")
def data_quality_results(context: AssetExecutionContext) -> MaterializeResult:
    return _run_script(context, "execute_openmetadata_data_quality_tests.py")


@asset(group_name="catalog", deps=[catalog_tables, knowledge_graph], retry_policy=_SERVICE_RETRY_POLICY,
       description="Syncs PostgreSQL -> Cube.js -> Neo4j lineage DAGs into OpenMetadata and Neo4j. Depends on knowledge_graph, not just catalog_tables, specifically because it writes lineage nodes into the same Neo4j graph knowledge_graph unconditionally wipes on every run -- ordering the other way would silently lose them on the next pipeline run.")
def lineage_dag(context: AssetExecutionContext) -> MaterializeResult:
    return _run_script(context, "sync_end_to_end_lineage.py")


# ----------------------------------------------------------------------------
# D. Retrieval Index (genuinely last)
# ----------------------------------------------------------------------------

@asset(group_name="retrieval", deps=[catalog_tables, data_contracts, fibo_groundings, postgres_superuser_synced], retry_policy=_SERVICE_RETRY_POLICY,
       description="Generates and indexes dense vector embeddings (catalog tables, data products, FIBO tags) into pgvector. Genuinely last: reads exactly the three catalog-side upstream assets it depends on here, and nothing depends on it -- see CLAUDE.md's own note on why this is the one step the prose-ordered pipeline listing got right by putting it last. Also depends on postgres_superuser_synced directly: unlike most pipeline scripts, this one writes to Postgres over a native psycopg2/TCP connection (see the C6 finding), which the postgres-password reset bug actually affects.")
def vector_embeddings(context: AssetExecutionContext) -> MaterializeResult:
    return _run_script(context, "generate_vector_embeddings.py")


full_pipeline_job = define_asset_job(
    name="full_pipeline",
    description="Materializes the entire data pipeline in one run, in real dependency order -- "
    "the Dagster-orchestrated equivalent of scripts/bootstrap_platform.sh's data-pipeline half. "
    "Independent assets (e.g. knowledge_graph, catalog_tables, and readonly_role_configured, which "
    "share only postgres_seeded as a dependency) run concurrently, not in the mostly-linear order "
    "the same steps used to be listed in.",
)

# H10 residual-gap fix (hardening plan), closed 2026-08-08: a job scoped to
# just the one asset, so the schedule below doesn't have to re-run (or wait
# on) the entire pipeline just to check whether a 90-day-bounded credential
# needs renewing. This -- not bootstrap_platform.sh's own call to the same
# script -- is the actual "nothing automates re-minting it" gap-closer: it
# fires on its own schedule regardless of when anyone next runs a bootstrap
# or materializes the full pipeline.
bot_token_rotation_job = define_asset_job(
    name="bot_token_rotation",
    selection=[bot_token_rotated],
    description="Checks/rotates the OpenMetadata ingestion-bot JWT (H10). Idempotent -- a no-op "
    "most days; only actually mints and writes a new token when the current one is missing or "
    "within 14 days of its 90-day expiry.",
)

bot_token_rotation_schedule = ScheduleDefinition(
    name="bot_token_rotation_daily",
    job=bot_token_rotation_job,
    # Once a day comfortably clears the token's own 90-day expiry and this
    # asset's own 14-day renewal threshold with wide margin -- even if a run
    # is missed for a few days (the daemon isn't running, the host is off),
    # there's no realistic way to miss the whole 14-day window unnoticed.
    cron_schedule="0 6 * * *",
    execution_timezone="UTC",
)

defs = Definitions(
    assets=[
        synthetic_seed_data,
        postgres_seeded,
        postgres_superuser_synced,
        readonly_role_configured,
        knowledge_graph,
        bot_token_rotated,
        catalog_tables,
        pii_tags_and_profiles,
        fibo_groundings,
        data_contracts,
        data_quality_results,
        lineage_dag,
        vector_embeddings,
    ],
    jobs=[full_pipeline_job, bot_token_rotation_job],
    schedules=[bot_token_rotation_schedule],
)
