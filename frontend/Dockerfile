FROM nginx:1.27-alpine

# Build-time version stamp: docker build --build-arg APP_VERSION=2.0 ...
ARG APP_VERSION=1.0
# UPSTREAM = <service-name>:<port> of the backend. Override with an env var in the Deployment.
# (Not called API_PORT etc. on purpose: Kubernetes injects API_PORT for a Service named "api"!)
ENV APP_VERSION=${APP_VERSION} \
    UPSTREAM=api:5000

# The official image renders /etc/nginx/templates/*.template -> /etc/nginx/conf.d/ at startup
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY index.html /usr/share/nginx/html/index.html
RUN sed -i "s/__APP_VERSION__/${APP_VERSION}/g" /usr/share/nginx/html/index.html

EXPOSE 80
