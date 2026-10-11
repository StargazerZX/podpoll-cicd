#!/usr/bin/env bash
# Run the API test suite locally, including the Postgres integration tests.
#
#   scripts/test-api.sh            # unit + Postgres tests (starts a throwaway postgres container)
#   scripts/test-api.sh --no-pg    # unit tests only (no Docker needed)
#   scripts/test-api.sh -k vote    # extra args go straight to pytest
#
# Needs Python 3.12 (python3.12 on PATH, or uv) and, for the pg tests, Docker.
set -euo pipefail
cd "$(dirname "$0")/../api"

PG=1
if [[ "${1:-}" == "--no-pg" ]]; then PG=0; shift; fi

VENV=.venv
if [[ ! -x "$VENV/bin/python" ]]; then
  if command -v uv >/dev/null; then uv venv -q --python 3.12 "$VENV"; else python3.12 -m venv "$VENV"; fi
fi
if command -v uv >/dev/null; then
  uv pip install -q --python "$VENV/bin/python" --require-hashes -r requirements.txt -r requirements-dev.txt
else
  "$VENV/bin/pip" install -q --require-hashes -r requirements.txt -r requirements-dev.txt
fi

if [[ "$PG" == 1 ]]; then
  NAME=podpoll-pg-test
  PORT="${PG_TEST_PORT:-55432}"
  # Same image as local/compose.yaml; a throwaway, test-only password.
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run -d --rm --name "$NAME" -p "127.0.0.1:${PORT}:5432" \
    -e POSTGRES_USER=podpoll -e POSTGRES_PASSWORD=test-only -e POSTGRES_DB=podpoll \
    "${POSTGRES_IMAGE:-postgres:17.11-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24}" \
    -c cluster_name=pg-test >/dev/null
  trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
  for _ in $(seq 1 30); do
    docker exec "$NAME" pg_isready -h 127.0.0.1 -U podpoll -d podpoll >/dev/null 2>&1 && break
    sleep 1
  done
  export PG_TEST_HOST=127.0.0.1 PG_TEST_PORT="$PORT" PG_TEST_PASSWORD=test-only
fi

"$VENV/bin/python" -m pytest "$@"
