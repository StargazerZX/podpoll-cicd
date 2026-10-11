# Pinned versions

Every third-party version the repo depends on, and how it is pinned. **Rule:** tags are for humans,
digests/hashes/checksums are what gets used.

- Container images: `name:tag@sha256:<digest>`
- Python packages: exact version **and** hash in `requirements*.txt` (`pip install --require-hashes`)
- npm packages: exact version in `package.json` + `integrity` hash in `package-lock.json` (`npm ci`)
- GitHub Actions (solution branches): full commit SHA with a `# vX.Y.Z` comment
- Binaries downloaded in pipelines: verified against the publisher's checksum

**Cooldown:** a new release is adopted only after it has been public for **at least 7 days**
(Dependabot's `cooldown` setting enforces the same on the solution branches). Fresh releases are where
supply-chain compromises live, as in the March 2026 `trivy-action` tag hijack (CVE-2026-33634).
For base images the cooldown applies to the *version* (e.g. Python 3.12.15). Official images are
rebuilt every few days for OS patches, so their digests are always recent.

**Banned (CVE-2026-33634):** Trivy `0.69.4`–`0.69.6`, `aquasecurity/trivy-action` `0.0.1`–`0.34.2`,
`aquasecurity/setup-trivy` < `0.2.6`.

Looked up on **2026-10-11**.

## Container images

| Image | Tag | Digest (multi-arch index) | Tag published | Used in |
|---|---|---|---|---|
| python | `3.12.15-slim` (Debian trixie) | `sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1` | 2026-10-09 | `api/Dockerfile`, `node-agent/Dockerfile`, fake ECS metadata (`local/compose.yaml`) |
| nginxinc/nginx-unprivileged | `1.30.5-alpine-slim` (nginx stable) | `sha256:3af0c10d960cc2502427fe1219c52989d309e7d65596869c60a34fd2fa2406f0` | 2026-10-05 | `frontend/Dockerfile` |
| redis | `7.4.11-alpine` | `sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499` | 2026-09-21 | `local/compose.yaml` |
| postgres | `17.11-alpine` (17 on purpose, see context pack §C6) | `sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24` | 2026-09-21 | `local/compose.yaml`, `scripts/test-api.sh` |
| mcr.microsoft.com/playwright | `v1.63.0-noble` | `sha256:eff16c30e6f3f4af0a03fa4b706120d5e9b0891c344a27d64559aff5900a4a27` | with 1.63.0 | `scripts/test-e2e.sh` |

Why `alpine-slim` for the frontend: the full `alpine` variant bundles nginx's optional modules and their
libraries. On 2026-10-11 it carried a fixable HIGH (CVE-2026-4775, libtiff) that a Phase 3 Trivy gate would
fail on. `alpine-slim` is core nginx only.

## Python (api/requirements.txt, hashed; Python 3.12)

| Package | Version | Note |
|---|---|---|
| flask | 3.1.3 | |
| werkzeug | 3.1.9 | via flask |
| jinja2 / markupsafe / itsdangerous / click / blinker | 3.1.6 / 3.0.4 / 2.2.0 / 8.5.0 / 1.9.0 | via flask |
| gunicorn | 26.2.0 | 24+ opens a control socket by default; disabled in `gunicorn.conf.py` |
| redis | 8.1.0 | `setex` is deprecated, so the code uses `set(..., ex=)` |
| psycopg / psycopg-binary | 3.3.6 | |
| packaging, typing-extensions | 26.3, 4.16.0 | transitive |

Test-only (`api/requirements-dev.txt`, hashed): pytest 9.1.1, pytest-cov 7.1.0, coverage 7.16.2,
fakeredis 2.39.0, jsonschema 4.26.0.

`trivy fs api/` on 2026-10-11: 0 vulnerabilities in `requirements.txt`.

To change a dependency, edit `requirements.in` / `requirements-dev.in`, then:

```bash
uv pip compile --universal --python-version 3.12 --generate-hashes api/requirements.in -o api/requirements.txt
```

## npm (frontend/package.json, test tooling only)

| Package | Version | Note |
|---|---|---|
| @playwright/test | 1.63.0 | 1.64.0 (2026-10-07) was inside the 7-day cooldown |

## Maintainer workstation tools (not used by the app; for reference)

Installed on the build machine on 2026-10-11, each verified against the publisher's checksum or GitHub's
release-asset digest: gh 2.102.0, gitleaks 8.30.1, trufflehog 3.99.2, kustomize 5.8.3, actionlint 1.7.12,
hadolint 2.15.1, shellcheck 0.11.0, yq 4.54.1, uv 0.13.0, zizmor 1.30.1, Node 24.21.0 LTS,
Python 3.12.15 (via uv). Already present: Docker 29.8.2 / Compose v5.6.0, Terraform 1.16.5,
AWS CLI 2.36.28, kubectl 1.36.4, Helm 3.21.4, Trivy 0.74.0, pre-commit 4.6.2, ruff 0.15.0 (via uvx).
The versions the **pipelines** use are pinned on the solution branches and added here phase by phase.
