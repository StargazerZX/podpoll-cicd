#!/usr/bin/env bash
# scripts/smoke-test.sh -- "is the release I just deployed really live, and does it work?"
#
#   scripts/smoke-test.sh http://localhost:8081
#   scripts/smoke-test.sh "$ALB_URL" --expect-sha "$GITHUB_SHA" --expect-env dev --timeout 300
#
# Options:
#   --expect-sha SHA       both tiers must report this commit (catches "deployed, but old tasks still serve")
#   --expect-version VER   the frontend's /version must equal VER
#   --expect-env ENV       the API's environment must be ENV (catches a dev frontend wired to a prod API)
#   --timeout SECONDS      keep retrying until the expectations hold (default 120)
#   --no-vote              skip the write test (e.g. against prod)
# Needs: curl, jq. Exit code 0 = healthy release, 1 = not.
set -euo pipefail

BASE="${1:?usage: smoke-test.sh <base-url> [--expect-sha SHA] [--expect-version V] [--expect-env E] [--timeout S] [--no-vote]}"
BASE="${BASE%/}"; shift
SHA="" VERSION="" ENV_NAME="" TIMEOUT=120 VOTE=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --expect-sha) SHA="$(printf '%s' "$2" | tr 'A-F' 'a-f')"; shift 2;;
    --expect-version) VERSION="$2"; shift 2;;
    --expect-env) ENV_NAME="$2"; shift 2;;
    --timeout) TIMEOUT="$2"; shift 2;;
    --no-vote) VOTE=0; shift;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done
command -v jq >/dev/null || { echo "smoke-test: needs jq" >&2; exit 2; }

get() { curl -fsS --max-time 5 "$BASE$1"; }
last_error=""

check_once() {
  local info build fe_build fe_version
  get /healthz >/dev/null                                || { last_error="frontend /healthz not OK"; return 1; }
  info="$(get /api/info)"                                || { last_error="/api/info failed (is the API up and reachable from the frontend?)"; return 1; }
  [[ "$(jq -r .db_ok <<<"$info")" == "true" ]]           || { last_error="API reports its vote store unreachable"; return 1; }
  if [[ -n "$ENV_NAME" ]]; then
    local env; env="$(jq -r '.env // .namespace' <<<"$info")"
    [[ "$env" == "$ENV_NAME" ]]                          || { last_error="API env is '$env', expected '$ENV_NAME'"; return 1; }
  fi
  if [[ -n "$VERSION" ]]; then
    fe_version="$(get /version | tr -d '\n')"
    [[ "$fe_version" == "$VERSION" ]]                    || { last_error="frontend version is '$fe_version', expected '$VERSION'"; return 1; }
  fi
  if [[ -n "$SHA" ]]; then
    build="$(get /api/build)"; fe_build="$(get /build.json)"
    [[ "$(jq -r .git_sha <<<"$build")" == "$SHA" ]]      || { last_error="API serves $(jq -r .git_sha_short <<<"$build"), expected ${SHA:0:7}"; return 1; }
    [[ "$(jq -r .git_sha <<<"$fe_build")" == "$SHA" ]]   || { last_error="frontend serves $(jq -r .git_sha_short <<<"$fe_build"), expected ${SHA:0:7}"; return 1; }
  fi
  return 0
}

echo "smoke-test: $BASE (timeout ${TIMEOUT}s)"
deadline=$(( $(date +%s) + TIMEOUT ))
until check_once; do
  if (( $(date +%s) >= deadline )); then echo "FAIL: $last_error" >&2; exit 1; fi
  echo "  waiting: $last_error"
  sleep 5
done
echo "  ok: healthy, store reachable${ENV_NAME:+, env=$ENV_NAME}${VERSION:+, version=$VERSION}${SHA:+, both tiers at ${SHA:0:7}}"

if (( VOTE )); then
  option="$(get /api/results | jq -r '.results[0].option')"
  before="$(get /api/results | jq -r .total)"
  curl -fsS --max-time 5 -X POST -H 'Content-Type: application/json' \
    -d "$(jq -cn --arg o "$option" '{option: $o}')" "$BASE/api/vote" >/dev/null || { echo "FAIL: POST /api/vote failed" >&2; exit 1; }
  after="$(get /api/results | jq -r .total)"
  (( after > before )) || { echo "FAIL: vote was accepted but the total did not increase ($before -> $after)" >&2; exit 1; }
  echo "  ok: vote for '$option' counted ($before -> $after)"
fi
echo "PASS"
