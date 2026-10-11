#!/usr/bin/env bash
# Install the maintainer's local git hooks (they are NOT committed config, so forks never get them).
# pre-commit: on branch `main`, run guard-main.sh. Other branches are not checked.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
HOOK="$(git rev-parse --git-path hooks)/pre-commit"
cat > "$HOOK" <<'HOOK'
#!/usr/bin/env bash
if [[ "$(git rev-parse --abbrev-ref HEAD)" == "main" ]]; then
  exec scripts/maintainer/guard-main.sh
fi
HOOK
chmod +x "$HOOK"
echo "installed $HOOK"
