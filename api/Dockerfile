# PodPoll API image.
# Base pinned by DIGEST (the tag is for humans; the digest is what actually gets pulled).
# Renovate/Dependabot bump both together. See docs/versions.md.
FROM python:3.12.15-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
# --require-hashes: every package (and every transitive one) must match a hash in the lock
# file, so a tampered or swapped upload on PyPI fails the build instead of shipping.
COPY requirements.txt .
RUN pip install --require-hashes --no-deps -r requirements.txt
COPY app.py gunicorn.conf.py ./

# Build provenance, stamped by CI (scripts/version.sh). Declared AFTER the dependency layer so
# a new commit only rebuilds the last few layers. Defaults keep a plain `docker build` working.
ARG APP_VERSION=1.0 \
    GIT_SHA=unknown \
    GIT_REF=unknown \
    BUILD_ID=local \
    BUILD_URL= \
    CI_SYSTEM=local \
    BUILD_TIME=unknown \
    SOURCE_URL=
ENV APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA} \
    GIT_REF=${GIT_REF} \
    BUILD_ID=${BUILD_ID} \
    BUILD_URL=${BUILD_URL} \
    CI_SYSTEM=${CI_SYSTEM} \
    BUILD_TIME=${BUILD_TIME} \
    SOURCE_URL=${SOURCE_URL}
LABEL org.opencontainers.image.title="podpoll-api" \
      org.opencontainers.image.description="PodPoll API (Flask + gunicorn)" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.licenses="MIT"

# Non-root, by number (no passwd entry needed; Kubernetes runAsNonRoot can verify a numeric UID).
USER 10001:10001
EXPOSE 5000

# Liveness only (/healthz never checks Redis/Postgres). python:slim has no curl/wget.
# Compose overrides this with /readyz so dependants wait for a working store.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=2)"]

# gunicorn.conf.py: 2 workers, access log to stdout, CHAOS_START_DELAY_SECONDS hook.
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
