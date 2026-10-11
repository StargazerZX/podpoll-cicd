# PodPoll node-agent image (stdlib only). Same pinned base as the API: see docs/versions.md.
FROM python:3.12.15-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY agent.py .

ARG APP_VERSION=1.0 \
    GIT_SHA=unknown \
    BUILD_TIME=unknown \
    SOURCE_URL=
ENV APP_VERSION=${APP_VERSION}
LABEL org.opencontainers.image.title="podpoll-node-agent" \
      org.opencontainers.image.description="PodPoll node-agent: one heartbeat reporter per node/host/task" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.licenses="MIT"

USER 10001:10001

# Healthy while the report loop keeps turning (the alive file is touched every INTERVAL_SECONDS),
# even if the API is down: the agent's job is to keep trying, not to have succeeded.
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import os,sys,time; i=int(os.getenv('INTERVAL_SECONDS','10')); sys.exit(0 if time.time()-os.path.getmtime(os.getenv('ALIVE_FILE','/tmp/node-agent.alive')) < 3*i+5 else 1)"]

CMD ["python", "agent.py"]
