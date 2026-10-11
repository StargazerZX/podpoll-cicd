# labs/

| Script | What it does |
|---|---|
| `check-phase-N.sh` | checks that phase N is done in your fork, with a hint for every failing check |
| `apply.sh NN` | plants lab seed NN on a new branch `lab/NN-…` (staged, not committed) |
| `reset.sh` | throws the lab branch away and returns to where you started |
| `catch-up.sh N` | merges the reference solution for phase N into your branch (after a confirmation) |

**Lab seeds** (`NN-<name>/`) are deliberate problems for your pipeline to catch: a fake leaked key,
a vulnerable dependency, a risky workflow, a release that never becomes ready. Each has a `README.md`
(what to observe, how to fix it), the `seed.patch`, a `solution.patch` and a `check.sh`.
They are patches, not branches: a branch with a planted (fake) secret on GitHub would trip push protection.
Seeds arrive with the phases that use them (2–5).
