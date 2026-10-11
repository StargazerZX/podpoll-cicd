#!/usr/bin/env bash
# Run the Playwright smoke test against a running PodPoll, inside the official Playwright image
# (pinned by digest, same version as frontend/package.json), so no local browser install is needed.
#
#   scripts/test-e2e.sh                          # against http://localhost:8081 (local/up.sh dev)
#   BASE_URL=http://localhost:8082 scripts/test-e2e.sh
#   SCREENSHOT_DIR=docs/screenshots SCREENSHOT_NAME=dev scripts/test-e2e.sh screenshots
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="mcr.microsoft.com/playwright:v1.63.0-noble@sha256:eff16c30e6f3f4af0a03fa4b706120d5e9b0891c344a27d64559aff5900a4a27"
SHOTS=()
if [[ -n "${SCREENSHOT_DIR:-}" ]]; then
  mkdir -p "$SCREENSHOT_DIR"
  SHOTS=(-e "SCREENSHOT_DIR=/work/${SCREENSHOT_DIR}" -e "SCREENSHOT_NAME=${SCREENSHOT_NAME:-page}")
fi
# --network host: the browser must reach localhost:<port> of THIS machine.
docker run --rm --network host --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e "BASE_URL=${BASE_URL:-http://localhost:8081}" "${SHOTS[@]}" \
  -v "$PWD:/work" -w /work/frontend "$IMAGE" \
  sh -c 'npm ci --no-audit --no-fund --loglevel=error && npx playwright test "$@"' -- "$@"
