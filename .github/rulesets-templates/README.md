# Ruleset templates (import them in your fork)

GitHub → your fork → **Settings → Rules → Rulesets → New ruleset → Import a ruleset**.

| File | Use it with | What it enforces |
|---|---|---|
| `trunk.json` | trunk-based development | default branch: PR required (0 approvals, so you can merge your own), squash merges only, linear history, no force-push or deletion, required check `ci-ok` |
| `gitflow.json` | Gitflow | `main` **and** `develop`: PR required, merge commits, no force-push or deletion, required check `ci-ok` |
| `tags.json` | both | `v*` tags cannot be moved or deleted, so a release tag always means the same commit |

Import **one** of `trunk.json` / `gitflow.json`, plus `tags.json`.

**The required check `ci-ok`** is a job *you* write in Phase 1: the last job of your CI workflow,
which `needs:` every other job and fails unless they all succeeded. Requiring one aggregate job keeps
the ruleset stable while you add jobs (and avoids the trap where a *skipped* job counts as passing).
`integration_id: 15368` is the GitHub Actions app: only a check reported by Actions satisfies the rule,
not a commit status anyone with a token could post.

Until `ci-ok` has run once, GitHub can't offer it in the UI, but the imported ruleset already names it.
See `docs/branching/` for choosing between the two models.
