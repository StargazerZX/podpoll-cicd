#!/usr/bin/env bash
# labs/reset.sh [--yes] -- leave the current lab branch, back to where labs/apply.sh started,
# and delete the lab branch. Anything you did on the lab branch is DISCARDED (push it first if
# you want to keep it).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# shellcheck source=labs/_lib.sh
source labs/_lib.sh
[[ "${1:-}" == "--yes" ]] && YES=1

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[[ "$BRANCH" == lab/* ]] || die "You are on '${BRANCH}', not a lab/* branch. Nothing to reset."
ORIGIN_FILE="$(git rev-parse --git-path podpoll-lab-origin)"
ORIG="$(cat "$ORIGIN_FILE" 2>/dev/null || echo main)"
confirm "Discard branch '${BRANCH}' (and any uncommitted changes) and return to '${ORIG}'?" || exit 0
git switch --discard-changes "$ORIG"
git branch -D "$BRANCH"
rm -f "$ORIGIN_FILE"
ok "Back on '${ORIG}'. '${BRANCH}' deleted."
