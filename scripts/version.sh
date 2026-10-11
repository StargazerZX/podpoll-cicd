#!/usr/bin/env bash
# scripts/version.sh -- compute the build provenance for an image, the same way everywhere.
#
#   scripts/version.sh            # KEY=VALUE lines (dotenv). In GitHub Actions: >> "$GITHUB_ENV"
#   scripts/version.sh --json     # the same as one JSON object
#
# Prints: APP_VERSION GIT_SHA GIT_SHA_SHORT GIT_REF BUILD_ID BUILD_URL CI_SYSTEM BUILD_TIME
#         SOURCE_URL IMAGE_TAG
#
# Detects GitHub Actions (GITHUB_ACTIONS=true), Jenkins (JENKINS_URL) or a local shell.
# APP_VERSION rules:
#   * already set in the environment         -> used as is (sanitised)
#   * building a tag vX.Y.Z                  -> X.Y.Z
#   * anything else                          -> <VERSION file>-<branch>.<short sha>, e.g. 1.0.0-main.0a1b2c3
#                                               (+dirty when a local working tree has uncommitted changes)
# IMAGE_TAG is always immutable: sha-<first 12 chars of the commit>.
# shellcheck disable=SC2034  # the output variables are read indirectly, via ${!k}
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

FORMAT="env"
[[ "${1:-}" == "--json" ]] && FORMAT=json

sanitize() { # value allowed-bracket-body max-len  (same rules as api/app.py and frontend/stamp.sh)
  printf '%s' "$1" | LC_ALL=C sed "s/[^$2]/-/g" | cut -c1-"$3"
}

# Turn any git remote into a browsable https URL, and NEVER leak credentials into an image label:
#   git@github.com:u/r.git -> https://github.com/u/r ; https://user:token@host/u/r.git -> https://host/u/r
to_https() {
  local url="$1"
  url="${url%.git}"
  if [[ "$url" =~ ^git@([^:]+):(.+)$ ]]; then url="https://${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"; fi
  if [[ "$url" =~ ^ssh://git@([^/]+)/(.+)$ ]]; then url="https://${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"; fi
  url="$(printf '%s' "$url" | sed -E 's#^(https?://)[^/@]*@#\1#')"
  [[ "$url" =~ ^https?:// ]] && printf '%s' "$url" || true
}

git_or() { git -C "$ROOT" "$@" 2>/dev/null || true; }

if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  CI_SYSTEM=github-actions
  GIT_SHA="${GITHUB_SHA:-$(git_or rev-parse HEAD)}"
  GIT_REF="${GITHUB_REF:-unknown}"
  BUILD_ID="${GITHUB_RUN_NUMBER:-0}"
  [[ "${GITHUB_RUN_ATTEMPT:-1}" != "1" ]] && BUILD_ID="${BUILD_ID}.${GITHUB_RUN_ATTEMPT}"
  BUILD_URL="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
  SOURCE_URL="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}"
  # On pull_request events GITHUB_REF is refs/pull/N/merge: use the branch name for the version.
  BRANCH="${GITHUB_HEAD_REF:-${GITHUB_REF_NAME:-}}"
  TAG=""; [[ "${GITHUB_REF_TYPE:-}" == "tag" ]] && TAG="${GITHUB_REF_NAME}"
elif [[ -n "${JENKINS_URL:-}" ]]; then
  CI_SYSTEM=jenkins
  GIT_SHA="${GIT_COMMIT:-$(git_or rev-parse HEAD)}"
  BRANCH="${CHANGE_BRANCH:-${BRANCH_NAME:-${GIT_BRANCH:-}}}"
  TAG="${TAG_NAME:-}"
  GIT_REF="${TAG:+refs/tags/$TAG}"; GIT_REF="${GIT_REF:-refs/heads/${BRANCH:-unknown}}"
  BUILD_ID="${BUILD_NUMBER:-0}"
  BUILD_URL="${BUILD_URL:-}"
  SOURCE_URL="$(to_https "${GIT_URL:-$(git_or remote get-url origin)}")"
else
  CI_SYSTEM=local
  GIT_SHA="$(git_or rev-parse HEAD)"
  BRANCH="$(git_or rev-parse --abbrev-ref HEAD)"
  [[ "$BRANCH" == "HEAD" ]] && BRANCH=""
  TAG="$(git_or describe --tags --exact-match --match 'v*' HEAD)"
  GIT_REF="${TAG:+refs/tags/$TAG}"; GIT_REF="${GIT_REF:-${BRANCH:+refs/heads/$BRANCH}}"; GIT_REF="${GIT_REF:-unknown}"
  BUILD_ID=local
  BUILD_URL=""
  SOURCE_URL="$(to_https "$(git_or remote get-url origin)")"
fi

GIT_SHA="$(printf '%s' "${GIT_SHA:-}" | tr 'A-F' 'a-f')"
[[ "$GIT_SHA" =~ ^[0-9a-f]{40}$ ]] || GIT_SHA=unknown
GIT_SHA_SHORT=unknown; IMAGE_TAG=sha-unknown
if [[ "$GIT_SHA" != unknown ]]; then GIT_SHA_SHORT="${GIT_SHA:0:7}"; IMAGE_TAG="sha-${GIT_SHA:0:12}"; fi

if [[ -z "${APP_VERSION:-}" ]]; then
  if [[ "${TAG:-}" =~ ^v([0-9]+\.[0-9]+\.[0-9]+.*)$ ]]; then
    APP_VERSION="${BASH_REMATCH[1]}"
  else
    BASE="$(tr -d ' \n' < "$ROOT/VERSION" 2>/dev/null || echo 0.0.0)"
    SLUG="$(sanitize "${BRANCH:-detached}" '0-9A-Za-z.' 30)"
    APP_VERSION="${BASE}-${SLUG}.${GIT_SHA_SHORT}"
    if [[ "$CI_SYSTEM" == local && -n "$(git_or status --porcelain --untracked-files=no)" ]]; then
      APP_VERSION="${APP_VERSION}+dirty"
    fi
  fi
fi
APP_VERSION="$(sanitize "$APP_VERSION" '0-9A-Za-z.+-' 64)"
GIT_REF="$(sanitize "$GIT_REF" '0-9A-Za-z._/+-' 128)"
BUILD_ID="$(sanitize "$BUILD_ID" '0-9A-Za-z._-' 64)"
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

KEYS=(APP_VERSION GIT_SHA GIT_SHA_SHORT GIT_REF BUILD_ID BUILD_URL CI_SYSTEM BUILD_TIME SOURCE_URL IMAGE_TAG)
if [[ "$FORMAT" == json ]]; then
  for k in "${KEYS[@]}"; do printf '%s\0%s\0' "$k" "${!k}"; done |
    python3 -c 'import json,sys; p=sys.stdin.buffer.read().split(b"\0")[:-1]; print(json.dumps({p[i].decode(): p[i+1].decode() for i in range(0,len(p),2)}))'
else
  for k in "${KEYS[@]}"; do printf '%s=%s\n' "$k" "${!k}"; done
fi
