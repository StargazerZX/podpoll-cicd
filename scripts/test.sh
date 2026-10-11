#!/usr/bin/env bash
# Run every unit/integration test suite in the repo:
#   1. API (pytest + fakeredis; Postgres integration tests in a throwaway container) -- coverage >= 80%
#   2. node-agent (pytest)
#   3. scripts (security-report.py, against real scanner output)
#   4. frontend logic (node --test)
# The browser smoke test needs a running stack: local/up.sh dev && scripts/test-e2e.sh
#
#   scripts/test.sh            # everything
#   scripts/test.sh --no-pg    # skip the Postgres tests (no Docker needed)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> API"
scripts/test-api.sh "$@"
echo "==> node-agent"
api/.venv/bin/python -m pytest -q -p no:cacheprovider -o addopts="" node-agent/tests
echo "==> scripts (security-report.py)"
api/.venv/bin/python -m pytest -q -p no:cacheprovider -o addopts="" scripts/tests
echo "==> frontend (logic.js)"
node --test frontend/tests/logic.test.js
echo "==> all suites passed"
