#!/usr/bin/env bash
# labs/check-phase-0.sh [--aws] -- is your Phase 0 setup complete?
#
#   1. tools   2. your fork   3. PodPoll running locally with YOUR commit   4. (--aws) budget alert
# Start the app first:  local/up.sh dev
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1
# shellcheck source=labs/_lib.sh
source labs/_lib.sh
BASE="${BASE_URL:-http://localhost:8081}"
CHECK_AWS=0; [[ "${1:-}" == "--aws" ]] && CHECK_AWS=1

echo "${C_B}1. Tools${C_0}"
for t in git docker curl jq python3; do
  if command -v "$t" >/dev/null; then ok "$t found"; else bad "$t missing"; hint "install $t (see docs/labs/phase-0-setup.md)"; fi
done
if docker compose version >/dev/null 2>&1; then ok "docker compose v2 found"; else bad "docker compose (v2 plugin) missing"; fi
if docker info >/dev/null 2>&1; then ok "Docker daemon reachable"; else bad "Docker daemon not reachable"; hint "start Docker Desktop / the docker service"; fi

echo "${C_B}2. Your fork${C_0}"
ORIGIN="$(git remote get-url origin 2>/dev/null || true)"
if [[ -z "$ORIGIN" ]]; then
  bad "no 'origin' remote"; hint "clone YOUR fork: git clone git@github.com:<you>/podpoll-cicd.git"
elif [[ "$ORIGIN" == *StargazerZX/podpoll-cicd* ]]; then
  warn "origin is the upstream repository ($ORIGIN)"; hint "fork it on GitHub and clone your fork, or you can't push or run Actions (fine for the maintainer)"
else
  ok "origin = $ORIGIN"
fi
if git remote get-url upstream >/dev/null 2>&1; then ok "upstream remote set"; else warn "no 'upstream' remote"; hint "git remote add upstream $UPSTREAM_URL   (labs/catch-up.sh adds it for you)"; fi
if git ls-remote --exit-code --heads origin 'solution/*' >/dev/null 2>&1 || git ls-remote --exit-code --heads upstream 'solution/*' >/dev/null 2>&1; then
  ok "solution branches reachable"
else
  warn "no solution/* branches visible yet"; hint "normal until they are published; when forking, untick 'Copy the main branch only'"
fi

echo "${C_B}3. PodPoll running locally (${BASE})${C_0}"
if ! curl -fsS --max-time 3 "$BASE/healthz" >/dev/null 2>&1; then
  bad "nothing answers on $BASE"; hint "start it: local/up.sh dev"
else
  ok "frontend answers"
  INFO="$(curl -fsS --max-time 3 "$BASE/api/info" 2>/dev/null || true)"
  if [[ -n "$INFO" && "$(jq -r .db_ok <<<"$INFO")" == "true" ]]; then ok "API answers and Redis is reachable (env: $(jq -r .env <<<"$INFO"))"
  else bad "API not answering or store unreachable"; hint "docker compose -p podpoll-dev -f local/compose.yaml ps / logs api"; fi
  HEAD_SHA="$(git rev-parse HEAD)"
  RUN_SHA="$(curl -fsS --max-time 3 "$BASE/api/build" 2>/dev/null | jq -r .git_sha 2>/dev/null)"
  if [[ "$RUN_SHA" == "$HEAD_SHA" ]]; then ok "card 6 shows your current commit (${HEAD_SHA:0:7})"
  else warn "running build is ${RUN_SHA:0:7}, your HEAD is ${HEAD_SHA:0:7}"; hint "rebuild with local/up.sh dev to see your own commit in card 6"; fi
fi

if (( CHECK_AWS )); then
  echo "${C_B}4. AWS budget alert${C_0}"
  if ! command -v aws >/dev/null; then bad "aws CLI missing"; hint "install AWS CLI v2"
  elif ! ACCOUNT="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)"; then bad "AWS CLI not logged in"; hint "aws login   (or aws configure sso)"
  else
    COUNT="$(aws budgets describe-budgets --account-id "$ACCOUNT" --query 'length(Budgets)' --output text 2>/dev/null || echo 0)"
    if [[ "$COUNT" =~ ^[1-9] ]]; then ok "account $ACCOUNT has $COUNT budget(s)"; else bad "no AWS Budget in account $ACCOUNT"; hint "create one (docs/labs/phase-0-setup.md, task 5) BEFORE Phase 4"; fi
  fi
fi

echo
if (( FAILS )); then printf '%sPhase 0 not complete: %d check(s) failed.%s\n' "$C_R" "$FAILS" "$C_0"; exit 1; fi
printf '%sPhase 0 complete.%s Next: docs/labs/phase-1-basic-pipeline.md\n' "$C_G" "$C_0"
