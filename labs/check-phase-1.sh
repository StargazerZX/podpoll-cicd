#!/usr/bin/env bash
# labs/check-phase-1.sh [--branch NAME] -- is Phase 1 (your first pipeline) complete in your fork?
#
#   1. your workflow file(s): least-privilege permissions, triggers, pinned actions, the ci-ok job
#   2. the latest push run on your default branch is green
#   3. the three images for that commit exist on GHCR with an immutable sha- tag
#   4. a branch ruleset protects the default branch and requires ci-ok
#
# Uses the public GitHub API (no login needed for a public fork). Set GITHUB_TOKEN, or be logged in
# with `gh`, for higher rate limits. --branch checks another branch's runs (default: the default branch).
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1
# shellcheck source=labs/_lib.sh
source labs/_lib.sh
BRANCH=""
[[ "${1:-}" == "--branch" ]] && BRANCH="${2:-}"
command -v jq >/dev/null || die "needs jq"

ORIGIN="$(git remote get-url origin 2>/dev/null || true)"
if [[ "$ORIGIN" =~ github\.com[:/]([^/]+)/([^/]+)$ ]]; then
  OWNER="${BASH_REMATCH[1]}"; REPO="${BASH_REMATCH[2]%.git}"
else
  die "origin ($ORIGIN) is not a GitHub repository"
fi
OWNER_LC="$(printf '%s' "$OWNER" | tr '[:upper:]' '[:lower:]')"
API="https://api.github.com/repos/${OWNER}/${REPO}"
TOKEN="${GITHUB_TOKEN:-$(gh auth token 2>/dev/null || true)}"
gh_api() {
  local auth=(); [[ -n "$TOKEN" ]] && auth=(-H "Authorization: Bearer ${TOKEN}")
  curl -fsS -m 20 -H "Accept: application/vnd.github+json" "${auth[@]}" "$API$1"
}

echo "${C_B}Checking ${OWNER}/${REPO}${C_0}"
echo "${C_B}1. Workflow files${C_0}"
shopt -s nullglob
WF=(.github/workflows/*.yml .github/workflows/*.yaml)
if (( ${#WF[@]} == 0 )); then
  bad "no workflow in .github/workflows/"; hint "Task 2 of docs/labs/phase-1-basic-pipeline.md"
else
  for f in "${WF[@]}"; do
    if grep -qE '^permissions:' "$f"; then ok "$f declares top-level permissions"
    else bad "$f has no top-level 'permissions:'"; hint "add 'permissions: {}' at the top and grant per job"; fi
  done
  if grep -qE '^\s+pull_request:|^\s+- pull_request$|^on:.*pull_request' "${WF[@]}"; then ok "runs on pull requests"
  else bad "no pull_request trigger"; hint "PRs must be tested before they merge"; fi
  if grep -qE '^\s+push:|^\s+- push$' "${WF[@]}"; then ok "runs on pushes"; else bad "no push trigger"; fi
  UNPINNED="$(grep -hoE 'uses:\s*[^ #]+@[^ #]+' "${WF[@]}" | sed -E 's/uses:\s*//' | grep -vE '@[0-9a-f]{40}$' | grep -v '^\./' | sort -u)"
  if [[ -z "$UNPINNED" ]]; then ok "every action is pinned to a full commit SHA"
  else warn "actions pinned by tag (Phase 3 makes this a hard rule):"; while read -r u; do echo "      $u"; done <<<"$UNPINNED"; fi
  if grep -qE '^\s{2}ci-ok:' "${WF[@]}"; then ok "a ci-ok job exists"
  else bad "no 'ci-ok' job"; hint "the imported ruleset requires a check named ci-ok (Task 6)"; fi
fi

echo "${C_B}2. Latest run${C_0}"
REPO_JSON="$(gh_api "")" || die "cannot read ${API} (private fork? set GITHUB_TOKEN)"
DEFAULT="$(jq -r .default_branch <<<"$REPO_JSON")"
TARGET="${BRANCH:-$DEFAULT}"
RUN="$(gh_api "/actions/runs?branch=${TARGET}&event=push&per_page=1" | jq '.workflow_runs[0] // empty')"
SHA=""
if [[ -z "$RUN" ]]; then
  bad "no push run on '${TARGET}' yet"; hint "merge your workflow into ${TARGET} (or push to it) and wait for the run"
else
  SHA="$(jq -r .head_sha <<<"$RUN")"
  STATE="$(jq -r '.status + "/" + (.conclusion // "-")' <<<"$RUN")"
  URL="$(jq -r .html_url <<<"$RUN")"
  if [[ "$STATE" == "completed/success" ]]; then ok "run for ${SHA:0:7} on ${TARGET} is green: $URL"
  else bad "latest run on ${TARGET} is ${STATE}: $URL"; hint "open it, fix the first red step, push again"; fi
fi

echo "${C_B}3. Images on GHCR${C_0}"
if [[ -n "$SHA" ]]; then
  TAG="sha-${SHA:0:12}"
  for c in api frontend node-agent; do
    REF="ghcr.io/${OWNER_LC}/podpoll-${c}:${TAG}"
    if docker manifest inspect "$REF" >/dev/null 2>&1; then ok "$REF"
    else bad "$REF not found (or not readable)"; hint "package private? make it public in its Package settings, or: docker login ghcr.io"; fi
  done
else
  warn "skipped (no run to take the commit from)"
fi

echo "${C_B}4. Branch protection on '${DEFAULT}'${C_0}"
RULES="$(gh_api "/rules/branches/${DEFAULT}" 2>/dev/null || echo '[]')"
if jq -e 'map(.type) | index("pull_request")' <<<"$RULES" >/dev/null; then ok "pull requests required"
else bad "no ruleset requiring pull requests on ${DEFAULT}"; hint "import .github/rulesets-templates/trunk.json (or gitflow.json) in Settings → Rules"; fi
if jq -e '[.[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context] | index("ci-ok")' <<<"$RULES" >/dev/null; then ok "ci-ok is a required check"
else bad "ci-ok is not a required check"; hint "the imported template adds it; check the ruleset is 'Active', not 'Evaluate'"; fi

echo
if (( FAILS )); then printf '%sPhase 1 not complete: %d check(s) failed.%s\n' "$C_R" "$FAILS" "$C_0"; exit 1; fi
printf '%sPhase 1 complete.%s Run your pipeline-built images: see Task 7 of the guide.\n' "$C_G" "$C_0"
