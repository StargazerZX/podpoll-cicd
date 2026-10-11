#!/usr/bin/env bash
# Stop one PodPoll environment:  local/down.sh dev   (add -v to also delete the Postgres volume)
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_NAME="${1:-dev}"
[[ $# -gt 0 ]] && shift
# --profile "*": also stop profile-only services (postgres, ecs-metadata) whatever the env file enabled.
docker compose -p "podpoll-${ENV_NAME}" -f local/compose.yaml --profile "*" down "$@"
