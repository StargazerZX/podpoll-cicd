# Choosing a branching model

Pick **one** for your fork in Phase 1; the pipelines you write must support it (the reference solution
supports both, because its triggers cover `main`, `develop`, `release/**`, `hotfix/**` and `v*` tags).

| | [Trunk-based](trunk-based.md) | [Gitflow](gitflow.md) |
|---|---|---|
| Long-lived branches | `main` | `main`, `develop` |
| Release = | a tag on `main` | merging `release/*` into `main`, then a tag |
| Feedback speed | fastest | slower (more hops) |
| Best for | continuous deployment, small teams | scheduled releases, multiple supported versions |
| Ruleset template | `trunk.json` | `gitflow.json` |

Not sure? Choose trunk-based: it's what most teams that deploy continuously use, and it keeps the pipeline simpler.
