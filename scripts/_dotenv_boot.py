#!/usr/bin/env python3
"""
===============================================================================
Shared .env Loader
===============================================================================
Every script in this repo reads credentials via `os.getenv(...)`, with the
convention that a missing variable yields an empty string rather than a
hardcoded fallback (see CLAUDE.md's Secrets convention). That convention only
does its job if `.env` actually gets loaded into the process environment first
-- and nothing did that: there was no `python-dotenv` dependency and no script
called `load_dotenv()`, so any script run directly on the host (which is how
every script in `scripts/` and `mcp_server/` is documented to run) silently saw
empty values for every credential unless the shell's environment happened to
already export them.

Call `load_env()` once near the top of a script's imports, before any
`os.getenv()` call that needs a value from `.env`. It's safe to call from
multiple modules in the same process (idempotent) and safe to call from a
module that itself has no `.env` values to read.
===============================================================================
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _REPO_ROOT / ".env"
_loaded = False


def load_env() -> None:
    """Load `.env` from the repo root into the process environment, once per process.

    Real environment variables already set (e.g. by Docker's `environment:` block,
    or exported in the shell) always take precedence and are never overridden --
    this only fills in values `.env` provides that aren't already set.
    """
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        # python-dotenv isn't installed (e.g. a minimal container image that never
        # runs scripts needing .env directly, or a fresh checkout that hasn't run
        # `pip install -r requirements.txt` yet). Fall back to whatever the real
        # environment already provides -- this matches the platform's existing
        # fail-closed convention (empty os.getenv default, not a fabricated one)
        # rather than crashing scripts that don't strictly need it.
        return
    load_dotenv(dotenv_path=_ENV_PATH, override=False)
