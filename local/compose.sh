#!/usr/bin/env bash
# Run any `docker compose` command against one PodPoll environment, with the same project name,
# compose file and env files local/up.sh uses:
#   local/compose.sh dev ps
#   local/compose.sh dev logs -f api
#   local/compose.sh dev up -d --scale api=3 --no-recreate
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_NAME="${1:?usage: local/compose.sh <env> <docker compose args...>}"; shift
ENV_FILE="local/env/${ENV_NAME}.env"
[[ -f "$ENV_FILE" ]] || { echo "No ${ENV_FILE}." >&2; exit 1; }
BUILD_ENV=()
[[ -f local/.build.env ]] && BUILD_ENV=(--env-file local/.build.env)
exec docker compose -p "podpoll-${ENV_NAME}" -f local/compose.yaml "${BUILD_ENV[@]}" --env-file "$ENV_FILE" "$@"
