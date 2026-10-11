#!/usr/bin/env bash
# scripts/maintainer/guard-main.sh -- fail if STUDENT-WRITTEN work is about to land on `main`.
#
# `main` is the Phase 0 starter that every student forks. Pipelines, scanner configs, deploy
# definitions and IAM trust policies are the learning objectives: they live ONLY on the
# solution/phase-N branches. A workflow on main would also run in every fork and give away Phase 1.
#
#   scripts/maintainer/guard-main.sh          # checks tracked + staged + untracked (non-ignored) files
#   scripts/maintainer/install-hooks.sh       # runs this automatically before every commit on main
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

mapfile -t FILES < <(git ls-files --cached --others --exclude-standard | sort -u)
violations=()
flag() { violations+=("$1  <- $2"); }

for f in "${FILES[@]}"; do
  [[ -e "$f" ]] || continue            # deleted in the working tree
  base="${f##*/}"
  case "$f" in
    .github/workflows/*.yml|.github/workflows/*.yaml) flag "$f" "GitHub Actions workflow (students write these)";;
    .github/dependabot.yml|.github/dependabot.yaml)   flag "$f" "Dependabot config (Phase 3 task)";;
    deploy/k8s/overlays/*)                            flag "$f" "Kustomize overlay (Phase 5 task)";;
    deploy/argocd/*)                                  flag "$f" "Argo CD object (Phase 5 task)";;
    deploy/ecs/*.json)                                flag "$f" "ECS task definition (Phase 4 task)";;
    security/README.md)                               ;;
    security/*)                                       flag "$f" "scanner config in security/ (Phases 2-3)";;
  esac
  case "$base" in
    Jenkinsfile|Jenkinsfile.*|*.Jenkinsfile)          flag "$f" "Jenkinsfile (Jenkins track task)";;
    .pre-commit-config.yaml|.pre-commit-config.yml)   flag "$f" "pre-commit config (Phase 2 task)";;
    sonar-project.properties)                         flag "$f" "SonarQube config (Phase 2 task)";;
    .gitleaks.toml|gitleaks.toml|.gitleaksignore)     flag "$f" "Gitleaks config (Phase 2 task)";;
    trivy.yaml|.trivyignore|.trivyignore.yaml)        flag "$f" "Trivy config (Phase 3 task)";;
    CODEOWNERS)                                       flag "$f" "CODEOWNERS (repo governance task)";;
  esac
  # IAM deploy roles: the GitHub OIDC trust CONDITION is the learning objective. The provided
  # Terraform may create the OIDC provider, but must not contain a filled-in `...:sub` condition.
  if [[ "$f" == infra/terraform/*.tf ]] && grep -q 'token.actions.githubusercontent.com:sub' "$f"; then
    flag "$f" "filled-in IAM deploy-role trust policy (Phase 4 task; leave the TODO skeleton)"
  fi
done

if (( ${#violations[@]} )); then
  echo "guard-main: student-written files found. These belong on solution/phase-N branches only:" >&2
  printf '  %s\n' "${violations[@]}" >&2
  exit 1
fi
echo "guard-main: OK (${#FILES[@]} files checked, no student-written work on this tree)"
