#!/usr/bin/env bash
# labs/apply.sh NN -- plant lab seed NN (e.g. 01) on a fresh branch lab/NN-<name>.
#
# A seed is a deliberate problem (a fake leaked key, a vulnerable dependency, a risky workflow...)
# that one of your pipeline's gates should catch. The changes are applied and STAGED, not
# committed: committing them is part of the exercise (your pre-commit hook may refuse!).
# Read labs/NN-*/README.md for what to observe and how to fix it. Undo with labs/reset.sh.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# shellcheck source=labs/_lib.sh
source labs/_lib.sh

shopt -s nullglob
SEEDS=(labs/[0-9][0-9]-*/)
ID="${1:-}"; [[ "$ID" =~ ^[0-9]{2}$ ]] || die "usage: labs/apply.sh NN   (available: ${SEEDS[*]:-none yet})"
DIRS=(labs/"${ID}"-*/)
[[ ${#DIRS[@]} -eq 1 ]] || die "No lab seed ${ID} (yet). Seeds arrive with Phases 2-5."
DIR="${DIRS[0]%/}"; NAME="${DIR#labs/}"
require_clean_tree

ORIG="$(git rev-parse --abbrev-ref HEAD)"
git switch -c "lab/${NAME}"
printf '%s\n' "$ORIG" > "$(git rev-parse --git-path podpoll-lab-origin)"
if [[ -x "$DIR/seed.sh" ]]; then
  "$DIR/seed.sh"                       # seeds that need more than a patch (e.g. a commit + a revert)
else
  git apply --index "$DIR/seed.patch"
fi
echo
ok "Seed ${NAME} planted on branch lab/${NAME} (you came from '${ORIG}')."
echo "Next: read ${DIR}/README.md"
