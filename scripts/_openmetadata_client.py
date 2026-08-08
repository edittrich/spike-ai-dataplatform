#!/usr/bin/env python3
"""
===============================================================================
Shared OpenMetadata REST Client
===============================================================================
Single implementation of api_get/api_put/api_post, previously redefined
across 7 files (16 function definitions total, per the Q10 finding) with
divergent error handling -- some swallowed connection failures into an
unhandled traceback, others didn't guard against a PUT/POST returning an
empty or non-JSON body. This is the union of the most defensive version of
each that existed across those 7 copies, plus a fix Q10 called out
specifically: OPENMETADATA_URL is read from the environment (with the
documented .env.example default) in every caller now, rather than being
hardcoded in 6 of the 9 places that referenced it, which meant the value in
`.env`/docker-compose.yml was silently ignored by most of the pipeline.

IMPORTANT for callers: OPENMETADATA_URL/JWT_TOKEN below are read at *import
time*, so this module must be imported *after*
`scripts._dotenv_boot.load_env()` has run in the importing script --
importing it earlier silently captures an empty JWT_TOKEN (same caveat as
`_neo4j_conn.py` and `_embedding_backend.py`).
===============================================================================
"""

import json
import os
import urllib.error
import urllib.request
from typing import Optional

OPENMETADATA_URL = os.getenv("OPENMETADATA_URL", "http://127.0.0.1:8585/api/v1")
JWT_TOKEN = os.getenv("OPENMETADATA_JWT_TOKEN", "")
if not JWT_TOKEN:
    print("⚠️ OPENMETADATA_JWT_TOKEN is not set; OpenMetadata API calls will be unauthenticated.")

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {JWT_TOKEN}",
}


def _request(
    method: str, endpoint: str, payload: Optional[dict] = None, timeout: int = 10
) -> Optional[dict]:
    """Issues one OpenMetadata REST call. Returns the parsed JSON body, a
    `{"status": "success", ...}` placeholder for an empty/non-JSON 2xx body,
    or None on any connection/HTTP failure (logged here; callers should
    treat None as "this call failed", not as an empty-but-successful result)."""
    url = f"{OPENMETADATA_URL}/{endpoint}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {"status": "success"}
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"status": "success", "raw": raw}
    except urllib.error.HTTPError as e:
        print(f"❌ Error {method} {endpoint}: {e.code} - {e.read().decode('utf-8')}")
        return None
    except urllib.error.URLError as e:
        # Connection refused / DNS failure / timeout -- none of the 7
        # original copies of this function caught this at all, so an
        # OpenMetadata outage surfaced as an unhandled traceback instead of
        # the same clean "could not reach the API" outcome an HTTPError gets.
        print(f"❌ Error {method} {endpoint}: could not reach {OPENMETADATA_URL} ({e.reason})")
        return None


def api_get(endpoint: str) -> Optional[dict]:
    """GET https://<OPENMETADATA_URL>/<endpoint>. See _request's docstring
    for the return contract."""
    return _request("GET", endpoint)


def api_put(endpoint: str, payload: dict) -> Optional[dict]:
    """PUT https://<OPENMETADATA_URL>/<endpoint> with a JSON body -- the
    idempotent create-or-update every OpenMetadata entity type supports.
    See _request's docstring for the return contract."""
    return _request("PUT", endpoint, payload)


def api_post(endpoint: str, payload: Optional[dict] = None) -> Optional[dict]:
    """POST https://<OPENMETADATA_URL>/<endpoint>, e.g. to trigger an
    application (SearchIndexingApplication) rather than create an entity.
    See _request's docstring for the return contract."""
    return _request("POST", endpoint, payload)
