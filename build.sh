#!/usr/bin/env bash
# Build every PodPoll image on your laptop, then load them into ALL nodes of your minikube cluster.
#
#   ./build.sh                      # default minikube profile
#   MINIKUBE_PROFILE=podpoll ./build.sh
#   DOCKER=podman ./build.sh        # if you use podman instead of docker
#
# Run this in a NORMAL shell (do not run `eval $(minikube docker-env)` first).
# Why not docker-env? Recent minikube versions default to containerd, and with several nodes
# docker-env would only reach ONE node. `minikube image load` copies to every node.
set -euo pipefail
cd "$(dirname "$0")"

DOCKER="${DOCKER:-docker}"
mk() { minikube ${MINIKUBE_PROFILE:+-p "$MINIKUBE_PROFILE"} "$@"; }

echo "==> Checking that minikube is running..."
mk status >/dev/null || { echo "minikube is not running. Start it first (see README)."; exit 1; }

echo "==> Building PodPoll images (v1.0 and v2.0 of api + frontend, v1.0 of node-agent)..."
for v in 1.0 2.0; do
  "$DOCKER" build -q -t "podpoll-api:$v"      --build-arg "APP_VERSION=$v" api/
  "$DOCKER" build -q -t "podpoll-frontend:$v" --build-arg "APP_VERSION=$v" frontend/
done
"$DOCKER" build -q -t podpoll-node-agent:1.0 node-agent/

# Third-party images used in the labs. Pre-loading them means the workshop does not depend on
# conference Wi-Fi (and avoids Docker Hub rate limits when 20 laptops pull at once).
THIRD_PARTY="redis:7-alpine busybox:1.36 nginx:1.27-alpine postgres:17-alpine"
echo "==> Pulling third-party images: $THIRD_PARTY"
for img in $THIRD_PARTY; do "$DOCKER" pull -q "$img"; done

echo "==> Loading images into every minikube node (this takes a minute)..."
for img in podpoll-api:1.0 podpoll-api:2.0 podpoll-frontend:1.0 podpoll-frontend:2.0 \
           podpoll-node-agent:1.0 $THIRD_PARTY; do
  echo "    loading $img"
  mk image load "$img"
done

echo "==> Done. Images now inside the cluster:"
mk image ls | grep -E "podpoll|redis|busybox|nginx|postgres" || true
