#!/usr/bin/env bash
# ==============================================================================
# gitleaks pre-commit hook (C7's residual gap: "add gitleaks or detect-secrets
# as a pre-commit hook and a CI job" -- the CI half already exists as an
# informational step in .github/workflows/ci.yml; this is the blocking half).
#
# Scans only the *staged* diff (`gitleaks protect --staged`), not full
# history -- fast enough to run on every commit, and deliberately narrower in
# scope than CI's informational full-history scan (see that step's own
# comment for why full-history scanning stays CI-only: this repo's history
# was already deliberately purged once per C7, so re-scanning it on every
# commit would be redundant cost for no new signal).
#
# Runs via Docker (the official `zricethezav/gitleaks` image, pinned to the
# same version CI implicitly gets from `gitleaks/gitleaks-action@v3`'s
# bundled binary at the time this was written) rather than requiring a
# locally-installed `gitleaks` binary or a Go toolchain -- consistent with
# how every other tool in this platform is invoked, and zero-install for a
# new contributor beyond Docker itself, which the whole platform already
# requires.
#
# Exits non-zero (blocking the commit) if a likely secret is found in the
# staged diff. False positive? Either fix the finding, or if it's genuinely
# not a secret (e.g. a high-entropy test fixture), add a targeted
# `.gitleaksignore` entry or an inline `# gitleaks:allow` comment -- do not
# disable this hook wholesale.
# ==============================================================================
set -euo pipefail

GITLEAKS_IMAGE="zricethezav/gitleaks:v8.30.1"
REPO_ROOT="$(git rev-parse --show-toplevel)"

exec docker run --rm \
  -v "${REPO_ROOT}:/repo" \
  -w /repo \
  "${GITLEAKS_IMAGE}" \
  protect --staged --source /repo --redact -v
