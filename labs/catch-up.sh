#!/usr/bin/env bash
# labs/catch-up.sh N [--yes] -- adopt the reference solution for phase N into your current branch.
#
# Merges upstream's solution/phase-N (which contains phases 1..N). Use it when you fell behind and
# want to start the next phase from a working state. It is a normal merge: you can inspect it with
# `git log --stat -1` and undo it with `git reset --hard ORIG_HEAD` before pushing.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# shellcheck source=labs/_lib.sh
source labs/_lib.sh

N="${1:-}"; [[ "$N" =~ ^[1-5]$ ]] || die "usage: labs/catch-up.sh <phase 1-5> [--yes]"
[[ "${2:-}" == "--yes" ]] && YES=1
require_clean_tree
ensure_upstream
git fetch --quiet upstream "solution/phase-${N}" || die "Could not fetch upstream solution/phase-${N}."

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
cat <<MSG
${C_B}About to merge the reference solution for phase ${N} into '${BRANCH}'.${C_0}
It brings in the pipelines/configs of phases 1..${N}. Where you already wrote your own versions of the
same files, git will report conflicts: keep yours, take theirs, or combine them, then commit.

Tip: finishing your own version teaches far more. Peek at single commits instead:
  git log --oneline upstream/solution/phase-${N}
  git show <commit>
MSG
confirm "Merge upstream/solution/phase-${N} now?" || { echo "Nothing changed."; exit 0; }
git merge --no-ff -m "catch-up: adopt the reference solution for phase ${N}" "upstream/solution/phase-${N}"
echo
ok "Merged. Review with: git log --stat -1   Undo (before pushing): git reset --hard ORIG_HEAD"
echo "Push when ready: git push origin ${BRANCH}"
