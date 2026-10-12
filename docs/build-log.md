# Build log

What was run to build and verify each milestone, what passed, what failed, and what could not be run.
"Verified" here always means "executed", never "should work".

---

## M0 (part 1): the Phase 0 application, run locally (2026-10-11)

**Scope of this entry:** the app changes from plan §4 (API, frontend, node-agent), hardened images,
the local Docker Compose stack, tests, helper scripts, `guard-main.sh`.
**Not in this entry:** see part 2 below.

**Machine:** Fedora 44, kernel 7.2.8, Docker 29.8.2 (rootful, iptables+firewalld), Compose v5.6.0.

### 1. The original app under real Docker (gap noted in the context pack)

The context pack's Compose file had only been checked with `docker compose config`. It was run for real,
unchanged, from the verbatim baseline commit:

| Check | Result |
|---|---|
| `docker compose -p podpoll-dev --env-file env/dev.env up -d --build` | **Failed once** with `failed to create network ...: COMMAND_FAILED: 'handle'` (a firewalld error on the host). A plain `docker network create` then worked, and the same `up` succeeded on retry. Host issue, not an app issue. |
| All 5 containers healthy; every §A3.2 endpoint through the frontend | PASS. Shapes match the pack; `/api/cluster/pods` shows the documented UNAVAILABLE message; 2 API replicas share the traffic |
| Postgres mode (`env/prod-postgres.env`, 3 replicas) | PASS: `store: postgres`, `db_server: prod-postgres`, vote stored |

Conclusion: the pack's untested Compose path works as written. No fixes were needed.

### 2. Tests (`scripts/test.sh`)

| Suite | Result |
|---|---|
| API: pytest + fakeredis, 74 tests | PASS |
| API: Postgres integration (`-m pg`, real `postgres:17.11-alpine` container), 5 tests including the concurrent schema race (8 forked processes behind a barrier) | PASS |
| API coverage on `app.py` | **99%** (gate: 80%) |
| API responses validated against `api/contracts/*.schema.json` | PASS |
| `stamp.sh` ↔ `app.py` sanitising parity (7 hostile inputs) | PASS |
| node-agent: pytest, 5 tests | PASS |
| frontend `logic.js`: `node --test`, 9 tests | PASS |
| **Total** | **93 passed, 0 failed** |

### 3. Images

| Check | api | frontend | node-agent |
|---|---|---|---|
| `hadolint` | PASS | PASS | PASS |
| `trivy config` (CRITICAL/HIGH/MEDIUM) | clean | clean | clean |
| `trivy image --severity CRITICAL,HIGH --ignore-unfixed` | 0 | 0 (after the fix below) | 0 |
| Runs as | uid 10001:10001 | uid 101:101 | uid 10001:10001 |
| Read-only root filesystem (Compose `read_only: true`, `cap_drop: ALL`) | works | works | works |
| Docker HEALTHCHECK | healthy | healthy | healthy |
| Size | 224 MB | 29 MB | 177 MB |

Also: `trivy config local/` clean; `gitleaks dir .` and `gitleaks git .` found no leaks;
`ruff check .` (rules in `ruff.toml`) clean; `shellcheck` clean on every script.

Problems found and fixed on the way:

1. **gunicorn 26 control socket.** gunicorn 24+ creates `$HOME/.gunicorn` for a control socket. As uid
   10001 with no home directory it logged `Control server error: [Errno 13] Permission denied: '/.gunicorn'`.
   Fixed with `control_socket_disable = True` in `gunicorn.conf.py`.
2. **libtiff HIGH in the frontend base.** `nginx-unprivileged:1.30.5-alpine` carried CVE-2026-4775 (fixable),
   which the Phase 3 gate would fail on a clean `main`. Switched to the `alpine-slim` variant (no optional
   modules, so no libtiff). Re-scanned: 0 fixable CRITICAL/HIGH. The image also went from 90 MB to 29 MB (measured).
3. **Site files owned by nginx.** `COPY --from=stamp` kept the build stage's uid 101, so the runtime user could
   modify the HTML. Fixed with `--chown=0:0`; verified `touch` fails with "Permission denied".
4. **`+` in a Docker tag.** `scripts/version.sh` produces versions like `1.0.0-main.2e6095e+dirty`, and using
   that as a local image tag failed (`invalid reference format`). Local tags now fall back to `IMAGE_TAG`
   (`sha-<12>`).
5. **redis-py 8 deprecates `setex`.** It produced a DeprecationWarning in the tests. Replaced with
   `set(key, value, ex=ttl)`, which has the same semantics.
6. **Agent name in ECS simulation.** Compose always set `NODE_NAME`, so the agent ignored the task metadata.
   Now an empty `NODE_NAME` counts as unset, and Compose uses `${NODE_NAME-docker-host}`.
7. **`local/down.sh` left Postgres running.** Without the env file, the `postgres` profile was inactive, so
   `down` skipped that container (and its network). Now it runs `down --profile "*"`; verified that
   `local/down.sh prod-postgres -v` leaves no container, network or volume behind.

### 4. The local stack (`local/up.sh`)

All four environments ran **at the same time** on one host:

| Environment | URL | Containers | `scripts/smoke-test.sh` | Playwright smoke | Screenshot |
|---|---|---|---|---|---|
| dev | :8081 | all healthy | PASS (`--expect-sha <HEAD> --expect-env dev --expect-version 2.0`) | PASS | [phase0-dev.png](screenshots/phase0-dev.png) |
| prod | :8082 | all healthy, 3 API replicas | n/a | PASS | [phase0-prod.png](screenshots/phase0-prod.png) |
| ecs-sim | :8083 | all healthy | n/a | PASS | [phase0-ecs-sim.png](screenshots/phase0-ecs-sim.png) |
| staging | :8084 | all healthy | n/a | PASS | [phase0-staging.png](screenshots/phase0-staging.png) |
| prod-postgres | :8086 (port overridden locally) | all healthy | PASS (`--expect-env prod`) | not run | none |

What the screenshots show (checked by eye, not only by the tests):

| Plan item | Seen |
|---|---|
| Badge colours dev / staging / prod (§4.2) | green / orange / red |
| Themes v1 / v2 / v3 (§4.1) | sky (prod) / amber + "FRONTEND v2" ribbon (dev) / emerald + "FRONTEND v3" ribbon (staging) |
| Card 6 "What's running?" | version, linked commit `2e6095e`, "local build", CI `local`, build age; both tiers |
| Card 7 "Release security" | shown only on staging (sample summary): PASS, gate, per-tool table, "2 finding(s) accepted as risk" |
| ECS mode (§4.3, fake metadata endpoint) | identities are task IDs, node is "eu-central-1c / FARGATE", task definition `podpoll-dev-api:7`, card 3 titled "Tasks (each task is its own micro-VM)", RBAC card hidden |
| RBAC card hidden off Kubernetes | hidden on all four |
| Platform-aware copy, no "Module N" | yes (also asserted in `logic.test.js`) |
| CSP blocks nothing of ours | Playwright saw zero console errors on all four |

Other runtime checks:

| Check | Result |
|---|---|
| Security headers on `/` and `/api/*` (CSP, nosniff, Referrer-Policy, X-Frame-Options, Permissions-Policy, COOP, CORP; `Server: nginx` without a version) | PASS (curl + Playwright) |
| Chaos run (`CHAOS_READY_FAIL=true CHAOS_START_DELAY_SECONDS=8 CHAOS_ERROR_RATE=0.5`) | log line `chaos: delaying startup by 8.0s`; frontend returned 502 for the first seconds; `/readyz` 503 while `/healthz` 200; 10 of 20 votes returned 500; the container never became healthy |
| `smoke-test.sh` negative case (prod URL, `--expect-env dev`) | FAIL as intended: `API env is 'prod', expected 'dev'` |
| `local/up.sh` guardrails | unknown env name lists the available ones; missing `prod-postgres.env` and empty `DB_PASSWORD` both stop with a clear message |
| `local/env/prod-postgres.env` git-ignored | yes (`git check-ignore`) |
| `guard-main.sh` | PASS on the tree; with 6 planted student files (workflow, Jenkinsfile, `security/trivy.yaml`, ECS task definition, `.gitleaksignore`, a filled-in OIDC trust condition) it failed and named every one |
| `scripts/version.sh` in GitHub Actions / Jenkins / local mode (simulated env vars) | correct in all three; tag `v1.4.2` → `1.4.2`; credentials in a Jenkins `GIT_URL` are stripped |

### 5. Not run, and why

| Item | Why |
|---|---|
| `local/compose.registry.yaml` against a real registry | validated with `docker compose config` only; it gets a real run in Phase 1, when a pipeline pushes images |
| Mixed-release chip in the browser | covered by unit tests (`isMixedRelease`); every local stack builds both tiers from one commit, so the chip never appears |
| `RESET_TOKEN` prompt in the browser | API side covered by tests; the UI's `window.prompt` path was not clicked through |
| Anything on Kubernetes, AWS, GitHub or Jenkins | outside this entry's scope |
| A fork-based "student" run | the user will do this manually later |

**AWS cost:** $0 (nothing created).

---

## M0 (part 2): Kubernetes base, security report, rulesets, labs, Phase 0 guide (2026-10-11)

**Decision (user, 2026-10-11):** GitHub Actions is the main track. The Jenkins stack and Jenkinsfile
solutions are deferred to a later optional alternate path, so they are not part of M0.

### 1. `deploy/k8s/base` (Kustomize)

| Check | Result |
|---|---|
| `kustomize build` + `kubeconform -strict` (Kubernetes 1.34 schemas) | 10/10 resources valid |
| `trivy config` | 0 CRITICAL, 0 HIGH; 1 MEDIUM (KSV-0023 hostPath `/var/log/pods`, accepted and documented); LOWs only for "no namespace" (overlays set it) and the images' own uids 101/999 |
| Overlay `namespace:` rewrites the RoleBinding's ServiceAccount subject | yes (`subject-ns=podpoll-dev`) |
| **Real deploy** on a throwaway 2-node minikube (Kubernetes v1.35.1, profile `podpoll-test`, deleted afterwards) via a test overlay | all pods Running on both nodes with non-root, read-only rootfs, `drop: ALL`, RuntimeDefault seccomp |
| `scripts/smoke-test.sh` through `kubectl port-forward` | PASS |
| Playwright smoke test | PASS, no console errors |
| Screenshot | [phase0-kubernetes.png](screenshots/phase0-kubernetes.png): namespace badge, DaemonSet card with pods-per-node, RBAC ALLOWED listing 7 pods |

Problems found by the real deploy and fixed:

1. **Trivy KSV-0121 (HIGH): node-agent mounted the host's `/proc`.** Not needed: memory, load and uptime in
   `/proc` are not namespaced, so the container's own `/proc` shows the node's values. Removed the hostPath
   (and the matching mount in `local/compose.yaml`); verified the numbers still appear on Docker and Kubernetes.
2. **RBAC card listed 0 pods.** Kustomize's `labels` transformer only labels pod templates with
   `includeTemplates: true`. Added; the card then listed all 7 pods.
3. **pods-per-node was null.** `/var/log/pods` is `root:root 0750` on this kubelet, so uid 10001 got
   `Permission denied`. Added `supplementalGroups: [0]` (read-only mount, still non-root); counts appeared (12 and 6).
4. Placeholder image tags moved into the manifests (Trivy KSV-0013 checks the raw files, not the rendered output).

Not verified: EKS specifics (managed node group, AL2023 node `/var/log/pods` permissions). That happens in Phase 5.
Side effect on the build machine: `minikube start` switched the kubectl current context; after deleting the
profile, no current context is set (the user's own contexts `lab` and `podpoll` are untouched).

### 2. `scripts/security-report.py`

| Check | Result |
|---|---|
| 13 tests fed with **real** output captured from gitleaks 8.30.1, trufflehog 3.99.2, trivy 0.74.0 (fs, config, image, with `--show-suppressed`), zizmor 1.30.1 | PASS |
| Output validates against `api/contracts/security-summary.schema.json` | yes; 1.4 KB, fits an ECS env var |
| End to end: generated summary → `RELEASE_SECURITY_SUMMARY` → API → card 7 | works: [phase0-security-card-fail.png](screenshots/phase0-security-card-fail.png) |
| Fixtures contain no secrets | `gitleaks dir` and `trufflehog filesystem` on `scripts/tests/fixtures/`: 0 findings (TruffleHog copies the key into `SecretParts` too, so the fixtures keep a whitelist of fields) |

Learned from the real outputs: Trivy 0.74 writes suppressed findings to `ExperimentalModifiedFindings` and
removes them from `Vulnerabilities`; gitleaks omits ignored findings entirely (the report counts the
declared `.gitleaksignore` entries instead). **Not verified against a live tool yet:** the SonarQube
(`api/issues/search`, `qualitygates/project_status`) and ZAP baseline fixtures are hand-written from the
documented formats. Phases 2 and 3 replace them with captured output.

### 3. Ruleset templates

`trunk.json`, `gitflow.json` and `tags.json` validate against the request schema of
`POST /repos/{owner}/{repo}/rulesets` in GitHub's published OpenAPI description (a deliberately broken copy
was rejected, so the check is real). **Not verified:** an actual import into a GitHub repository (no GitHub
access used, as agreed); that happens in Phase 1.

### 4. `labs/` scripts

| Script | Test | Result |
|---|---|---|
| `check-phase-0.sh` | maintainer clone with dev running; and `BASE_URL` pointing at nothing | passes with expected warnings; fails with a hint and exit 1 |
| `apply.sh` / `reset.sh` | scratch clone with a throwaway seed 99: apply, then unknown seed, then reset | seed staged on `lab/99-demo`; clear error for a missing seed; back on `main`, branch deleted, clean tree |
| `catch-up.sh` | scratch clone against a fake local upstream with `solution/phase-1` | adds `upstream`, fetches, merges with a clear message and undo hint |
| shellcheck | all scripts | clean (it caught a real bug: `_lib.sh`'s colour variable `N` collided with `catch-up.sh`'s phase number `N`) |

### 5. Phase 0 lab guide (`docs/labs/phase-0-setup.md`)

Followed by the maintainer on this machine: Task 3 (up), Task 4 steps 1–7 (including scale-out, prod/staging/ecs-sim,
the chaos release and `version.sh`), and the check script. Fixed while following it: the scale command lacked
the env files and would have built differently named images, so `local/compose.sh <env> …` was added.
The AWS budget CLI command was checked offline only (both JSON arguments parse; the option names exist in the
installed AWS CLI's help). **Not done:** a run by someone other than the maintainer, from a real fork
(the user will do this later), and Task 5 against a real AWS account (postponed by the user).

### Tests after this entry

`scripts/test.sh`: API 79 + node-agent 5 + security-report 13 + frontend 9 = **106 passed**. `ruff`, `shellcheck`, guard clean.

**AWS cost:** $0.

---

## M1: Phase 1, a basic pipeline on GitHub Actions (2026-10-12)

**Delivered:** `solution/phase-1` (one commit per lab step: test → build → push → smoke → ci-ok → CODEOWNERS),
`docs/labs/phase-1-basic-pipeline.md`, `labs/check-phase-1.sh`, Phase 1 action pins in `docs/versions.md`.
Jenkins track: deferred (see the M0 part 2 decision).

### What ran

| Check | Result |
|---|---|
| actionlint 1.7.12 on every intermediate step of `ci.yml` (steps 1–5) | clean |
| zizmor 1.30.1 (`--offline`, default and `--persona=pedantic`) | clean, after one fix: `setup-node` v7 caches by default, flagged as cache-poisoning (HIGH, low confidence) in a workflow that publishes; set `package-manager-cache: false` |
| Each step commit's `ci.yml` is byte-identical to the linted version | yes |
| Rehearsal of the smoke job on the build machine (local registry on :5001 → `compose.registry.yaml` → `--wait` → `smoke-test.sh --expect-sha`) | PASS; this was also the first real run of `local/compose.registry.yaml` |
| **Real run on GitHub:** push of `solution/phase-1` → [run 38238653588](https://github.com/StargazerZX/podpoll-cicd/actions/runs/38238653588) | **all 6 jobs green on the first attempt:** test, build (api / frontend / node-agent), smoke (pushed images), ci-ok |
| GHCR: `ghcr.io/stargazerzx/podpoll-{api,frontend,node-agent}:sha-6a570a9ea55c` | exist, and are **pullable anonymously**: packages pushed by a public repository's workflow came out public, with no visibility change needed |
| Image labels (`docker buildx imagetools inspect`) | `revision` = the commit, `source` = the repository URL, `version` = `1.0.0-solution-phase-1.6a570a9`, `created` = the build time |
| The pipeline's images run locally via `compose.registry.yaml` | smoke test PASS; card 6 shows `github-actions`, build `#1` linking to the run, and the commit: [phase1-ghcr-images.png](screenshots/phase1-ghcr-images.png) |
| `labs/check-phase-1.sh` on `main` | fails with a hint for each missing piece (no workflow, no run, no ruleset), exit 1 |
| `labs/check-phase-1.sh --branch solution/phase-1` | workflow, run and images ✔; **ruleset checks ✘**, because no ruleset is imported in the upstream repository yet |
| Guide commands (the `version.sh` hint, `imagetools --format`) | run; the label command needed `.Image.Config.Labels` (capitalised) and was fixed |

### Not verified yet, and why

| Item | Why |
|---|---|
| The `pull_request` path (build without push, smoke skipped, ci-ok passes with smoke=skipped) | needs a PR, and no GitHub token is used here. Opening any PR against `main` in the repository exercises it |
| A `v*` tag build (`vX.Y.Z` image tag) | pushing a tag to the public upstream repository was not part of the go-ahead |
| Ruleset import and enforcement (Task 6 checkpoints) | GitHub UI step, done by the repository owner |
| A student following the guide from a real fork | to be done by the user |

### Design notes

- The reference workflow also triggers on `solution/**`, so each solution branch proves itself in the
  upstream repository (the plan's "each solution branch's own pipeline proves that branch works").
  It is commented as upstream-only and harmless in forks.
- `ci-ok` treats `smoke=skipped` as OK **only** for `pull_request` events, so a push run where smoke was
  skipped for any other reason fails the gate.

**AWS cost:** $0. GitHub: public repository, so Actions minutes and GHCR storage are free.
