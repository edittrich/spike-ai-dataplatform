#!/usr/bin/env python3
"""
===============================================================================
Rebuild OpenMetadata's OpenSearch Catalog Index (SearchIndexingApplication)
===============================================================================
Closes a real gap found live during a full `docker compose down`/`up --build`
redeploy: `openmetadata_search`'s data directory is a tmpfs mount by design
(`docker-compose.yml`'s own comment: "Search is a rebuildable projection of
MySQL, not this platform's source of truth"), so every container recreate
starts with an empty index -- `table_search_index` doesn't exist at all until
something repopulates it.

Five pipeline scripts already trigger a reindex as a side effect of their own
work (`automate_openmetadata_pii_and_profiling.py`, `ground_fibo_ontology_uris.py`,
`register_openmetadata_data_contracts.py`, `sync_end_to_end_lineage.py`,
`execute_openmetadata_data_quality_tests.py`), which is why a full
`bootstrap_platform.sh` run self-heals. Nothing repopulates it on a *bare*
`docker compose down`/`up`, `restart`, or crash-recreate with no pipeline
re-run -- exactly the operation this script exists for. Symptom without it:
`search_data_catalog`/`check_data_quality` (and any direct
`GET /api/v1/search/query`) return `HTTP 500 index_not_found_exception` even
though the catalog's actual entity data (MySQL) and the tables it describes
(Postgres) are both completely intact -- a different root cause than the
`OPENMETADATA_JWT_TOKEN`-unset 500 documented in the runbook's Known Issues,
producing a confusingly identical symptom.

Idempotent and safe to run any time -- triggering a reindex while the catalog
is already fully indexed just re-derives the same result. Polls
OpenMetadata's own `SearchIndexingApplication` run-status API rather than
guessing a sleep duration or querying OpenSearch directly: the trigger call
returns immediately (verified live: `HTTP 200 "Application Triggered"`, no
job data), and the real reindex runs asynchronously, observed live to take
~4s for this platform's 39-table catalog but with no documented upper bound
for a larger one -- see POLL_TIMEOUT_SECONDS. Querying status through
`openmetadata_server`'s own API (not OpenSearch's :9200 directly) also means
this script never needs OpenSearch network reachability, matching the
platform's existing pattern (`search_data_catalog` MCP tool does the same).
===============================================================================
"""

import logging
import os
import sys
import time
from typing import Any, Dict, Optional

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this script is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env  # noqa: E402

load_env()

# _openmetadata_client reads OPENMETADATA_URL/JWT_TOKEN at import time, so it
# must be imported after load_env() -- see its module docstring.
from scripts._openmetadata_client import api_get, api_post  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("RebuildSearchIndex")

APP_NAME = "SearchIndexingApplication"
POLL_INTERVAL_SECONDS = 3
# Generous relative to the ~4s observed for this platform's 39-table catalog --
# a larger deployment's reindex genuinely takes longer, and this must not
# report a false failure just because it ran a normal amount of time.
POLL_TIMEOUT_SECONDS = int(os.getenv("REINDEX_TIMEOUT_SECONDS", "300"))


def _latest_run() -> Optional[Dict[str, Any]]:
    """Returns the most recent SearchIndexingApplication run record (newest
    first per the API's own ordering, verified live), or None if the app has
    never run or the server didn't respond."""
    res = api_get(f"apps/name/{APP_NAME}/status?limit=1")
    if not res or not res.get("data"):
        return None
    return res["data"][0]


def rebuild_search_index() -> bool:
    """Triggers a fresh reindex and blocks until it completes. Returns True
    only on a genuine `status: success` run with zero failed records --
    never assumes success just because the HTTP trigger call returned 200,
    since that only means the async job was accepted, not that it finished
    or that it finished cleanly."""
    baseline = _latest_run()
    baseline_start = baseline.get("startTime") if baseline else None

    logger.info(f"Triggering {APP_NAME}...")
    trigger_res = api_post(f"apps/trigger/{APP_NAME}")
    if trigger_res is None:
        logger.error(
            f"Failed to trigger {APP_NAME} -- see the connection/HTTP error logged above. "
            "Is openmetadata_server reachable and OPENMETADATA_JWT_TOKEN valid?"
        )
        return False

    deadline = time.time() + POLL_TIMEOUT_SECONDS
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
        run = _latest_run()
        if run is None:
            continue
        # Wait for a run that started *after* our trigger -- comparing status
        # alone would risk reading a still-"success"-labeled record left over
        # from a previous run before ours has actually started.
        if run.get("startTime") == baseline_start:
            continue

        status = run.get("status")
        if status == "running":
            logger.info("  ...reindex in progress")
            continue
        if status == "success":
            stats = (run.get("successContext") or {}).get("stats", {}).get("jobStats", {})
            total = stats.get("totalRecords", "?")
            failed = stats.get("failedRecords", 0)
            if failed:
                logger.warning(f"Reindex completed with {failed} failed record(s) out of {total}.")
                return False
            logger.info(f"✅ Reindex complete: {total} records, 0 failed.")
            return True
        # "failed", "activeError", or any other terminal-but-not-success status.
        logger.error(f"Reindex ended with status={status!r} (expected 'success'): {run}")
        return False

    logger.error(
        f"Timed out after {POLL_TIMEOUT_SECONDS}s waiting for {APP_NAME} to complete. "
        "Set REINDEX_TIMEOUT_SECONDS higher for a larger catalog, or check "
        "`docker compose logs openmetadata_server` for what the app is doing."
    )
    return False


def main() -> None:
    print("🔄 Rebuilding OpenMetadata's OpenSearch catalog index...")
    print("=========================================================")
    ok = rebuild_search_index()
    if not ok:
        print("\n❌ Search index rebuild did not complete successfully -- see the error above.")
        sys.exit(1)
    print("\n✅ Search index rebuild complete -- search_data_catalog/check_data_quality are live.")


if __name__ == "__main__":
    main()
