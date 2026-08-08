#!/usr/bin/env python3
"""
===============================================================================
Rotate OpenMetadata's ingestion-bot JWT Token Before It Expires
===============================================================================
H10 (hardening plan) residual gap, closed 2026-08-08: the earlier H10 fix
minted a real, genuine `ingestion-bot` JWT (via OpenMetadata's own
`PUT /users/generateToken/{id}` API, deliberately given a real 90-day bound
rather than "Unlimited" so as not to repeat C7's original non-expiring-token
mistake) and set it as `OPENMETADATA_JWT_TOKEN` in `.env`. That closed the
"the token is empty" gap, but left a smaller, genuine one behind: nothing
re-minted it before it expired. This script is that renewal mechanism.

Idempotent and safe to run any time (part of why it's shaped as a "check,
then act" script rather than an unconditional rotate-on-every-run one, the
same idempotency discipline `sync_postgres_superuser_password.py` and
`configure_readonly_role.py` already use):
  1. Decodes the *current* `OPENMETADATA_JWT_TOKEN` from `.env` locally (no
     API call needed, and no signature verification either -- we trust our
     own `.env`, we're not accepting this token from an untrusted caller).
     If it's missing, malformed, already expired, or expiring within
     `RENEWAL_THRESHOLD_DAYS`, a rotation is needed.
  2. If not, this is a clean no-op -- exits 0 having made no changes at all.
  3. If a rotation is needed: logs in as the OpenMetadata local admin
     (`OPENMETADATA_ADMIN_EMAIL`/`OPENMETADATA_ADMIN_PASSWORD`, new env vars
     -- see .env.example; no fallback default, per this repo's secrets
     convention), looks up the `ingestion-bot` system bot's user id, and
     calls the same `generateToken` API the original manual fix used,
     requesting the same bounded 90-day expiry (never "Unlimited").
  4. Writes the new token back into `.env` in place (only the
     `OPENMETADATA_JWT_TOKEN=...` line is touched; every other line,
     comment, and ordering is preserved byte-for-byte).
  5. Best-effort recreates the `mcp_sidecar` container (`docker compose up
     -d mcp_sidecar`) so it picks up the new value immediately -- Compose
     only evaluates `${OPENMETADATA_JWT_TOKEN}` interpolation at container
     creation time, so the old token would otherwise keep being used until
     the next unrelated recreate. Wrapped in try/except and never fatal:
     this script also needs to run cleanly in contexts with no live Docker
     stack at all (e.g. a bare `python3 scripts/rotate_openmetadata_bot_token.py`
     right after `.env` is first created, before anything is started).

Wired into `scripts/bootstrap_platform.sh` (so every bootstrap re-checks/
rotates) and into `orchestration/definitions.py` as a Dagster asset with its
own daily schedule (so renewal doesn't depend on someone remembering to
re-run bootstrap or this script by hand within the 90-day window) -- see
that file's `bot_token_rotation_schedule` for the actual periodic-automation
half of this fix.
===============================================================================
"""

import base64
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this module is launched from.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from scripts._dotenv_boot import load_env  # noqa: E402

load_env()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("RotateOpenMetadataBotToken")

OPENMETADATA_URL = os.getenv("OPENMETADATA_URL", "http://127.0.0.1:8585/api/v1")
ADMIN_EMAIL = os.getenv("OPENMETADATA_ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.getenv("OPENMETADATA_ADMIN_PASSWORD", "")
CURRENT_TOKEN = os.getenv("OPENMETADATA_JWT_TOKEN", "")

BOT_NAME = "ingestion-bot"
# A genuine bound, matching the original manual fix -- deliberately never
# "Unlimited" (C7's original leaked credential had `"exp": null`; this repo
# doesn't repeat that mistake for its replacement).
NEW_TOKEN_EXPIRY = "90"
# Rotate proactively, not right at the deadline -- gives a human (or the
# Dagster schedule's next daily run) real margin if something about the
# rotation itself needs attention.
RENEWAL_THRESHOLD_DAYS = 14

ENV_FILE = REPO_ROOT / ".env"


def _decode_jwt_exp(token: str) -> Optional[int]:
    """Reads a JWT's `exp` claim without verifying the signature. We don't
    need to verify it -- this token came from our own `.env`, not an
    untrusted caller -- we just need to know when it expires."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # restore stripped base64 padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("exp")
    except (IndexError, ValueError, json.JSONDecodeError):
        return None


def _needs_rotation(token: str) -> tuple[bool, str]:
    """Returns (needs_rotation, human_readable_reason)."""
    if not token:
        return True, "OPENMETADATA_JWT_TOKEN is empty"
    exp = _decode_jwt_exp(token)
    if exp is None:
        return True, "current token is malformed (no readable exp claim)"
    days_left = (exp - time.time()) / 86400
    if days_left <= 0:
        return True, f"current token already expired {-days_left:.1f} days ago"
    if days_left <= RENEWAL_THRESHOLD_DAYS:
        return True, f"current token expires in {days_left:.1f} days (<= {RENEWAL_THRESHOLD_DAYS}-day threshold)"
    return False, f"current token still has {days_left:.1f} days left"


def _api_call(method: str, path: str, bearer: Optional[str] = None, body: Optional[dict] = None) -> dict:
    """One-off urllib call for the admin-login/generateToken flow -- deliberately
    NOT routed through scripts/_openmetadata_client.py's api_get/api_put/api_post,
    since those always sign requests with the (possibly expired) bot token from
    module-import time; this script instead needs a short-lived *admin session*
    token per call, which that shared client has no way to override per-request."""
    url = f"{OPENMETADATA_URL}/{path}"
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _mint_new_bot_token() -> str:
    """Logs in as the OpenMetadata local admin, looks up the ingestion-bot's
    user id, and generates a fresh, genuinely time-bounded JWT for it. Raises
    on any failure -- a rotation that silently doesn't happen is worse than
    one that fails loudly."""
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        raise RuntimeError(
            "OPENMETADATA_ADMIN_EMAIL/OPENMETADATA_ADMIN_PASSWORD are not set in .env -- "
            "cannot log in to mint a new bot token. See .env.example's comment on these vars."
        )

    login_body = {
        "email": ADMIN_EMAIL,
        # OpenMetadata's basic-auth login API requires the password
        # base64-encoded in the request body (confirmed live: a plaintext
        # password is rejected with "Password needs to be encoded in Base-64") --
        # this is transport encoding, not cryptographic protection, so it's
        # applied here rather than asking the .env value itself to be pre-encoded.
        "password": base64.b64encode(ADMIN_PASSWORD.encode("utf-8")).decode("ascii"),
    }
    login_resp = _api_call("POST", "users/login", body=login_body)
    admin_session_token = login_resp["accessToken"]

    bot = _api_call("GET", f"bots/name/{BOT_NAME}", bearer=admin_session_token)
    bot_user_id = bot["botUser"]["id"]

    gen_resp = _api_call(
        "PUT",
        f"users/generateToken/{bot_user_id}",
        bearer=admin_session_token,
        body={"JWTTokenExpiry": NEW_TOKEN_EXPIRY},
    )
    return gen_resp["JWTToken"]


def _update_env_file(new_token: str) -> None:
    """Rewrites only the OPENMETADATA_JWT_TOKEN= line in .env, in place --
    every other line (including comments and ordering) is preserved
    byte-for-byte, the same targeted-edit discipline the original manual
    fix used."""
    if not ENV_FILE.exists():
        raise RuntimeError(f"{ENV_FILE} does not exist -- nothing to update.")
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
    replaced = False
    for i, line in enumerate(lines):
        if line.startswith("OPENMETADATA_JWT_TOKEN="):
            lines[i] = f"OPENMETADATA_JWT_TOKEN={new_token}\n"
            replaced = True
            break
    if not replaced:
        # Shouldn't happen (.env.example always defines the line), but fail
        # loudly rather than silently appending a second, conflicting line.
        raise RuntimeError("No OPENMETADATA_JWT_TOKEN= line found in .env -- refusing to guess where to add one.")
    ENV_FILE.write_text("".join(lines), encoding="utf-8")


def _recreate_mcp_sidecar() -> None:
    """Best-effort only -- mcp_sidecar only needs recreating if it (and the
    rest of the Docker Compose stack) is actually running right now. Never
    raises: this script must also run cleanly with no stack up at all.

    Real bug, caught live while verifying this fix: if the invoking shell
    already `source`d an older `.env` (e.g. the `set -a; source .env; set
    +a` pattern CLAUDE.md itself documents before running a script), a
    stale OPENMETADATA_JWT_TOKEN sitting in *this process's own environment*
    -- inherited by the subprocess below -- takes precedence over the value
    Compose would otherwise read fresh from the just-updated `.env` file on
    disk (Compose's variable-substitution rules prefer a real process env
    var over `.env` file interpolation). Reproduced live: `docker compose up
    -d mcp_sidecar` returned exit 0 with no "Recreate" in its output, and
    the container kept running the old token. Fixed by stripping this one
    var from the subprocess's environment before the call, forcing Compose
    to fall back to reading the fresh value from `.env` on disk -- which is
    the value we actually just wrote and want it to use."""
    try:
        env = os.environ.copy()
        env.pop("OPENMETADATA_JWT_TOKEN", None)
        result = subprocess.run(
            ["docker", "compose", "up", "-d", "mcp_sidecar"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, env=env,
        )
        if result.returncode == 0:
            logger.info("✅ Recreated mcp_sidecar so it picks up the new token immediately.")
        else:
            logger.warning(
                "Could not recreate mcp_sidecar (exit %s) -- if the stack is running, restart it "
                "manually: docker compose up -d mcp_sidecar. Stderr: %s",
                result.returncode, result.stderr.strip()[-500:],
            )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.warning(
            "Could not run `docker compose up -d mcp_sidecar` (%s) -- if the stack is running, "
            "restart it manually so it picks up the new token.", e,
        )


def main() -> None:
    needs_it, reason = _needs_rotation(CURRENT_TOKEN)
    if not needs_it:
        logger.info(f"✅ No rotation needed -- {reason}.")
        return

    logger.info(f"Rotating OPENMETADATA_JWT_TOKEN -- {reason}.")
    try:
        new_token = _mint_new_bot_token()
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, RuntimeError) as e:
        logger.error(f"❌ Failed to mint a new bot token: {e}")
        sys.exit(1)

    _update_env_file(new_token)
    new_exp = _decode_jwt_exp(new_token)
    exp_str = time.strftime("%Y-%m-%d", time.gmtime(new_exp)) if new_exp else "unknown"
    logger.info(f"✅ Minted a new ingestion-bot token (expires {exp_str}) and wrote it to .env.")

    _recreate_mcp_sidecar()


if __name__ == "__main__":
    main()
