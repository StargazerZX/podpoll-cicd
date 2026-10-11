# Build log

What was run to build and verify each milestone, what passed, what failed, and what could not be run.
"Verified" here always means "executed", never "should work".

---

## M0 (part 1): the Phase 0 application, run locally (2026-10-11)

**Scope of this entry:** the app changes from plan §4 (API, frontend, node-agent), hardened images,
the local Docker Compose stack, tests, helper scripts, `guard-main.sh`.
**Not in this entry (rest of M0):** Kubernetes base (`deploy/k8s/base`), Jenkins stack, lab guide
`docs/labs/phase-0-setup.md`, `scripts/security-report.py`, `labs/` scripts, ruleset templates,
branching docs, fork test.

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
