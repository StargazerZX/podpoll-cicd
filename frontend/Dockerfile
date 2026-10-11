# PodPoll frontend image: static HTML/JS served by UNPRIVILEGED nginx (uid 101, port 8080).
# Base pinned by digest; see docs/versions.md. "alpine-slim" = core nginx only: none of the optional
# modules (image-filter, xslt, ...) and none of their libraries (libtiff, libxml2, ...) to patch.
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.30.5-alpine-slim@sha256:3af0c10d960cc2502427fe1219c52989d309e7d65596869c60a34fd2fa2406f0

# ---- stage 1: stamp the build provenance into the static files --------------------------------
FROM ${NGINX_IMAGE} AS stamp
ARG APP_VERSION=1.0 \
    GIT_SHA=unknown \
    GIT_REF=unknown \
    BUILD_ID=local \
    BUILD_URL= \
    CI_SYSTEM=local \
    BUILD_TIME=unknown \
    SOURCE_URL=
COPY --chmod=0755 stamp.sh /stamp.sh
COPY index.html app.js logic.js app.css /src/
RUN /stamp.sh /src /tmp/site

# ---- stage 2: the runtime image -----------------------------------------------------------------
FROM ${NGINX_IMAGE}
ARG APP_VERSION=1.0 \
    GIT_SHA=unknown \
    GIT_REF=unknown \
    BUILD_ID=local \
    BUILD_URL= \
    CI_SYSTEM=local \
    BUILD_TIME=unknown \
    SOURCE_URL=
# UPSTREAM = <service-name>:<port> of the backend; override per environment.
# (Not called API_PORT etc. on purpose: Kubernetes injects API_PORT for a Service named "api"!)
# NGINX_ENVSUBST_FILTER: only UPSTREAM is ever substituted into the nginx config, so no other
# environment variable (or a hostile value in one) can change it.
ENV UPSTREAM=api:5000 \
    NGINX_ENVSUBST_FILTER=^UPSTREAM$ \
    APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA} \
    GIT_REF=${GIT_REF} \
    BUILD_ID=${BUILD_ID} \
    BUILD_URL=${BUILD_URL} \
    CI_SYSTEM=${CI_SYSTEM} \
    BUILD_TIME=${BUILD_TIME} \
    SOURCE_URL=${SOURCE_URL}
LABEL org.opencontainers.image.title="podpoll-frontend" \
      org.opencontainers.image.description="PodPoll frontend (static UI + reverse proxy to the API)" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.licenses="MIT"

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
# Site files stay owned by root: nginx (uid 101) can read them but never modify them.
COPY --from=stamp --chown=0:0 /tmp/site/ /usr/share/nginx/html/

USER 101:101
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"]
