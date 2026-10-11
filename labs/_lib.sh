# Shared helpers for labs/*.sh (sourced, not executed).
# shellcheck shell=bash
UPSTREAM_URL="${PODPOLL_UPSTREAM_URL:-https://github.com/StargazerZX/podpoll-cicd.git}"

# shellcheck disable=SC2034  # colours are used by the scripts that source this file
if [[ -t 1 ]]; then C_G=$'\e[32m'; C_R=$'\e[31m'; C_Y=$'\e[33m'; C_B=$'\e[1m'; C_0=$'\e[0m'
else C_G=""; C_R=""; C_Y=""; C_B=""; C_0=""; fi
FAILS=0
ok()   { printf '%s✔%s %s\n' "$C_G" "$C_0" "$*"; }
bad()  { printf '%s✘%s %s\n' "$C_R" "$C_0" "$*"; FAILS=$((FAILS + 1)); }
warn() { printf '%s!%s %s\n' "$C_Y" "$C_0" "$*"; }
hint() { printf '    → %s\n' "$*"; }
die()  { printf '%s%s%s\n' "$C_R" "$*" "$C_0" >&2; exit 1; }

repo_root() { git rev-parse --show-toplevel 2>/dev/null || die "Run this inside your clone of the repository."; }
require_clean_tree() {
  [[ -z "$(git status --porcelain --untracked-files=no)" ]] || die "You have uncommitted changes. Commit or stash them first (git stash)."
}
confirm() { # confirm "question"  (skipped with --yes / YES=1)
  [[ "${YES:-0}" == 1 ]] && return 0
  read -r -p "$1 [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]]
}
ensure_upstream() {
  if ! git remote get-url upstream >/dev/null 2>&1; then
    echo "Adding remote 'upstream' -> $UPSTREAM_URL"
    git remote add upstream "$UPSTREAM_URL"
  fi
}
