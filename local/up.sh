#!/usr/bin/env bash
# Build and start one PodPoll environment on plain Docker.
#
#   local/up.sh dev                  # http://localhost:8081  (also: staging, prod, ecs-sim, prod-postgres)
#   local/up.sh prod --no-build      # extra args go to `docker compose up`
#   CHAOS_READY_FAIL=true local/up.sh dev
#
# It stamps real build provenance (git SHA, branch, build time) into the images via
# scripts/version.sh, so card 6 "What's running?" shows YOUR commit.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_NAME="${1:-dev}"
[[ $# -gt 0 ]] && shift
ENV_FILE="local/env/${ENV_NAME}.env"
if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "${ENV_FILE}.example" ]]; then
    echo "First copy ${ENV_FILE}.example to ${ENV_FILE} and fill in its values (that file is git-ignored)." >&2
  else
    envs=(local/env/*.env); envs=("${envs[@]#local/env/}")
    echo "No ${ENV_FILE}. Available: ${envs[*]%.env}" >&2
  fi
  exit 1
fi
if grep -q '^COMPOSE_PROFILES=.*postgres' "$ENV_FILE" && ! grep -Eq '^DB_PASSWORD=.+' "$ENV_FILE"; then
  echo "${ENV_FILE}: set DB_PASSWORD first (any local-only value)." >&2
  exit 1
fi

scripts/version.sh > local/.build.env
# build.env first, the environment file second: the environment file wins on conflicts.
docker compose -p "podpoll-${ENV_NAME}" -f local/compose.yaml \
  --env-file local/.build.env --env-file "$ENV_FILE" up -d --build "$@"

PORT="$(grep -E '^FRONTEND_PORT=' "$ENV_FILE" | cut -d= -f2)"
echo
echo "PodPoll ${ENV_NAME}: http://localhost:${PORT:-8080}"
echo "Stop it with:   local/down.sh ${ENV_NAME}"
