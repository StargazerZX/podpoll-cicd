# PodPoll: CI/CD Edition

A small three-tier voting app whose real job is to **make the platform visible**. Every card shows
which build is running, which instance answered, which environment it belongs to and where the votes live.
That makes pipelines, promotions, rollbacks and bad releases things you can **see** in the browser.

This repository is a hands-on **secure CI/CD workshop**. You fork it and, phase by phase, write the
pipelines, scanner configs and deployment code yourself:

| Phase | Theme | Where it runs |
|---|---|---|
| 0 | Set up, run the app locally | Docker |
| 1 | Basic pipeline: test, build, push, branching rules | GitHub Actions |
| 2 | Shift-left: pre-commit, Gitleaks, SonarQube | GitHub Actions |
| 3 | Trivy, TruffleHog, SBOMs, reports, a hardened pipeline | GitHub Actions |
| 4 | Deploy to Amazon ECS on Fargate (push-based CD) | GitHub Actions + your AWS account |
| 5 | GitOps with Argo CD on Amazon EKS (pull-based CD) | GitHub Actions + your AWS account |

GitHub Actions is the main track. A local Jenkins track for Phases 1–3 will follow later as an optional alternate path.

`main` is the starting point (Phase 0): the app, tests and helpers, but **no pipelines**. That's your job.
Reference solutions live on the `solution/phase-N` branches.

> **Start here:** [docs/labs/phase-0-setup.md](docs/labs/phase-0-setup.md).
> Status: Phase 0 is complete; Phase 1 (GitHub Actions) is next. See [docs/build-log.md](docs/build-log.md).

## Run it locally

You need Docker with the Compose plugin and Git.

```bash
local/up.sh dev        # builds the images and starts the stack: http://localhost:8081
local/down.sh dev      # stops it
local/compose.sh dev ps   # any docker compose command for one environment (ps, logs -f api, ...)
```

| Environment | Command | URL | What you see |
|---|---|---|---|
| dev | `local/up.sh dev` | http://localhost:8081 | green badge, v2 (amber) theme |
| prod | `local/up.sh prod` | http://localhost:8082 | red badge, v1 (sky) theme, 3 API replicas |
| ECS simulation | `local/up.sh ecs-sim` | http://localhost:8083 | each API container looks like a Fargate task |
| staging | `local/up.sh staging` | http://localhost:8084 | orange badge, v3 (emerald) theme, card 7 "Release security" |
| prod + Postgres | copy `local/env/prod-postgres.env.example` to `prod-postgres.env`, set `DB_PASSWORD`, run `local/up.sh prod-postgres` | port from the env file | votes stored in PostgreSQL |

`local/up.sh` stamps your commit, branch and build time into the images (via `scripts/version.sh`),
so card 6 "What's running?" shows **your** build. To run images a pipeline pushed instead, see
[local/compose.registry.yaml](local/compose.registry.yaml).

### Chaos switches

Set any of these (e.g. `CHAOS_READY_FAIL=true local/up.sh dev`) to simulate a bad release:

| Variable | Effect |
|---|---|
| `CHAOS_READY_FAIL=true` | `/readyz` returns 503. The container never becomes ready |
| `CHAOS_START_DELAY_SECONDS=20` | the API takes 20 s to start listening |
| `CHAOS_ERROR_RATE=0.2` | 20% of votes fail with HTTP 500 |

`/healthz` (liveness) ignores all of them.

## What's in the app

```text
Browser ──▶ frontend (unprivileged nginx :8080) ──/api/──▶ api (Flask/gunicorn :5000) ──▶ redis (votes + heartbeats)
                                                                 ▲                     └─▶ postgres (optional, votes)
                                                 node-agent ─────┘  heartbeats every 10 s
```

| Card | Shows |
|---|---|
| 1 · Vote | the poll (`POLL_QUESTION` / `POLL_OPTIONS`) and where votes are stored |
| 2 · Who answered me? | frontend and API instance, version, node, environment; a per-instance response histogram |
| 3 · Nodes / Tasks / Host | one row per node-agent (adapts to Kubernetes, ECS or Docker) |
| 4 · Where do my votes live? | Redis or PostgreSQL, and whether it's reachable |
| 5 · What can the API see? | Kubernetes RBAC (shown on Kubernetes only) |
| 6 · What's running? | version, commit, CI run, CI system and build age of each tier; flags a *mixed release* |
| 7 · Release security | the pipeline's scan summary for this release (shown only when the pipeline provides one) |

### API

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | liveness: process alive (never checks dependencies) |
| `GET /readyz` | readiness: can reach the active vote store |
| `GET /api/info` | who answered: instance, environment, platform, version, store, chaos flags |
| `GET /api/build` | build provenance: version, git SHA, ref, CI run, build time |
| `GET /api/results`, `POST /api/vote`, `POST /api/reset` | the poll (`RESET_TOKEN` optionally protects reset) |
| `POST /api/nodes/heartbeat`, `GET /api/nodes` | node-agent reports |
| `GET /api/cluster/pods` | Kubernetes RBAC probe |
| `GET /api/release/security` | the release's security summary (`RELEASE_SECURITY_SUMMARY` or `_FILE`) |

The frontend also serves `/version`, `/whoami` and `/build.json`. The JSON shapes are specified in
[api/contracts/](api/contracts/). Fields are only ever added, never removed.

## Tests

```bash
scripts/test.sh                                   # API (incl. Postgres in a container), node-agent, frontend logic
local/up.sh dev && scripts/test-e2e.sh            # Playwright browser smoke test, in a container
scripts/smoke-test.sh http://localhost:8081       # the post-deploy check pipelines will use
```

## Repository layout

```text
api/            Flask API, gunicorn config, hashed requirements, tests, JSON contracts
frontend/       static UI (index.html, app.js, logic.js, app.css), nginx config, stamp.sh, tests
node-agent/     heartbeat reporter (DaemonSet on k8s, sidecar on ECS), tests
local/          Docker Compose stack, env files, fake ECS metadata endpoint
scripts/        version.sh, smoke-test.sh, security-report.py, test runners; maintainer/ (guard-main.sh)
labs/           check-phase-N.sh, lab seeds (apply.sh / reset.sh), catch-up.sh
.github/        rulesets-templates/ (import into your fork); workflows/ is yours to write
security/       your scanner configs (Phases 2-3)
deploy/         Kubernetes base (Kustomize), reference CI deployer; ECS/overlays/Argo CD come in Phases 4-5
docs/           labs/ (the lab guides), branching/, versions.md, build-log.md, screenshots/
```

## Conventions worth knowing

- **No environment variable is called `<SERVICE>_PORT`.** Kubernetes injects those for every Service
  (a Service named `redis` injects `REDIS_PORT=tcp://…`), so the app uses `REDIS_TCP_PORT`, `DB_TCP_PORT`
  and `UPSTREAM` instead.
- **Everything is pinned:** images by digest, Python packages by hash. See [docs/versions.md](docs/versions.md).
- **Images run as non-root** and work with a read-only root filesystem.
