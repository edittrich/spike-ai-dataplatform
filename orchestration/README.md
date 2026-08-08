# Dagster Orchestration

Replaces the prose-only pipeline ordering in `CLAUDE.md`/`README.md` (and the imperative sequence
in `scripts/bootstrap_platform.sh`) with a real Dagster asset graph — Part 5 item 1 in the hardening
plan: *"the 8-step pipeline is run by hand, ordering encoded only in prose; no retries, backfill, or
run history."* See [`definitions.py`](definitions.py)'s module docstring for the full design
rationale (why each asset shells out to the existing script rather than importing its `main()`, why
infra startup is deliberately out of scope, and the one non-obvious dependency edge —
`lineage_dag` → `knowledge_graph` — the prose ordering never made explicit).

Runs on the **host**, alongside the other standalone pipeline scripts it orchestrates (not
containerized) — it needs to reach Postgres/Neo4j/OpenMetadata/Cube.js at their host-published
`127.0.0.1:<port>` addresses exactly the way a human running these scripts by hand already does.
Containerizing it would mean solving the same `network_mode: host` questions the rest of this
platform's services already carry (see the comment block at the top of `docker-compose.yml`) for no
benefit, since Dagster orchestrating *host-run* scripts is a completely ordinary way to use it.

## Setup

```bash
pip install -r orchestration/requirements.txt

# Dagster persists run history/logs/event storage under DAGSTER_HOME -- if
# unset, it falls back to a temp directory that's wiped on reboot, which
# would make the "run history" this item exists to provide illusory. Point
# it somewhere real and persistent:
export DAGSTER_HOME="$(pwd)/orchestration/.dagster_home"
mkdir -p "$DAGSTER_HOME"
```

Add the `export DAGSTER_HOME=...` line to your shell profile (or re-run it in every new shell before
using Dagster) — it's not read from `.env` because Dagster itself, not this platform's own Python
code, is what reads it, before any of this repo's `_dotenv_boot.py`-based loading ever runs.

## Prerequisites

Start PostgreSQL and the Docker Compose stack first — exactly the same prerequisite the pipeline
scripts already have when run by hand:

```bash
npm run supabase:start
docker compose up -d
```

## Usage

```bash
# Launches the Dagster UI (asset graph, run history, logs) on :3001 -- not the
# default :3000, which Grafana already uses in this platform.
dagster dev -f orchestration/definitions.py -p 3001
```

Open `http://127.0.0.1:3001`, select the `full_pipeline` job, and click **Materialize all**. Assets
that share only a common upstream dependency (e.g. `knowledge_graph`, `catalog_tables`, and
`readonly_role_configured`, which all depend only on `postgres_seeded`) run concurrently — the real
parallelism the previous linear, hand-run ordering never expressed. A failed asset can be retried
individually (each service-calling asset also carries its own automatic retry policy — 2 retries,
10s apart, for exactly the transient-connectivity case a fresh `docker compose up -d` often hits)
without re-running everything before it.

Equivalently, from the CLI:

```bash
dagster asset materialize -f orchestration/definitions.py --select '*'
```

## What this does *not* replace

`scripts/bootstrap_platform.sh` still exists and still works — it's the simpler, dependency-free path
for a first-time or CI-style bring-up (no `pip install -r orchestration/requirements.txt`, no
`DAGSTER_HOME`, no UI to open). This orchestration layer is for iterating on the pipeline afterward:
re-running one failed step, backfilling after a schema change, or watching real run history
accumulate across many runs, none of which the shell script provides.
