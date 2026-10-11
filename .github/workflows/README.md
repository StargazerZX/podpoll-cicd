# .github/workflows/: you write these

This folder is empty on purpose. Writing the pipelines **is** the workshop:

| Phase | You add | Guide |
|---|---|---|
| 1 | `ci.yml`: test, build the three images, push to GHCR on non-PR events, the `ci-ok` gate | [docs/labs/phase-1-basic-pipeline.md](../../docs/labs/phase-1-basic-pipeline.md) |
| 2 | Gitleaks and SonarQube jobs | `docs/labs/phase-2-…` |
| 3 | Trivy, TruffleHog, SBOMs, security reports, zizmor/actionlint, Dependabot | `docs/labs/phase-3-…` |
| 4 | the ECS deploy workflow (OIDC, promotion, rollback) | `docs/labs/phase-4-…` |
| 5 | the GitOps promotion workflow | `docs/labs/phase-5-…` |

Stuck? `labs/catch-up.sh N` merges the reference solution for phase N into your fork
(see the guide first; copying a solution teaches far less than finishing your own).
