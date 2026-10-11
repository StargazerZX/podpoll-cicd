#!/usr/bin/env bash
# deploy/k8s/reference/make-sa-kubeconfig.sh <namespace> <serviceaccount> [duration=1h]
#
# The token-based onboarding path for robots and CI pipelines: mint a short-lived,
# on-demand token for an EXISTING ServiceAccount (`kubectl create token`, not the old
# never-expiring Secret-token pattern) and wrap it in a stand-alone kubeconfig. No keys,
# no CSR, no approval step -- that's the whole point of tokens for machines.
#
# Usage:
#   deploy/k8s/reference/make-sa-kubeconfig.sh dev ci-deployer 1h
#
# Requires: kubectl (pointed at the target cluster), with permission to create tokens
# for the named ServiceAccount (cluster-admin can always do this).
set -euo pipefail

NAMESPACE="${1:?Usage: $0 <namespace> <serviceaccount> [duration=1h]}"
SERVICEACCOUNT="${2:?Usage: $0 <namespace> <serviceaccount> [duration=1h]}"
DURATION="${3:-1h}"

echo "==> Verifying the ServiceAccount exists"
if ! kubectl get serviceaccount "$SERVICEACCOUNT" -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "No ServiceAccount named '$SERVICEACCOUNT' in namespace '$NAMESPACE'." >&2
  echo "Create it first (see deploy/k8s/reference/ci-deployer.yaml for an example)." >&2
  exit 1
fi

OUT_DIR="./kubeconfigs"
mkdir -p "$OUT_DIR"
KUBECONFIG_OUT="$OUT_DIR/sa-${NAMESPACE}-${SERVICEACCOUNT}.kubeconfig"

echo "==> Requesting a token for ${NAMESPACE}/${SERVICEACCOUNT} (duration ${DURATION})"
# `kubectl create token` is the modern (1.24+) replacement for the old auto-created,
# never-expiring Secret token: this one is minted on the spot and expires on its own.
# Note: the API server may cap the actual lifetime below what you ask for (its
# --service-account-max-token-expiration flag), so don't assume you got the full duration.
TOKEN="$(kubectl create token "$SERVICEACCOUNT" -n "$NAMESPACE" --duration="$DURATION")"

echo "==> Fetching the cluster's CA certificate and API server address"
CA_FILE="$(mktemp)"
trap 'rm -f "$CA_FILE"' EXIT
# kube-root-ca.crt is the same CA in every namespace; reading it from "default" always works.
kubectl get configmap kube-root-ca.crt -n default -o jsonpath='{.data.ca\.crt}' > "$CA_FILE"
SERVER="$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')"

echo "==> Building $KUBECONFIG_OUT"
CONTEXT_NAME="${SERVICEACCOUNT}@podpoll"
kubectl config set-cluster podpoll \
  --server="$SERVER" --certificate-authority="$CA_FILE" --embed-certs=true \
  --kubeconfig "$KUBECONFIG_OUT" >/dev/null
kubectl config set-credentials "$SERVICEACCOUNT" \
  --token="$TOKEN" \
  --kubeconfig "$KUBECONFIG_OUT" >/dev/null
kubectl config set-context "$CONTEXT_NAME" \
  --cluster=podpoll --user="$SERVICEACCOUNT" --namespace="$NAMESPACE" \
  --kubeconfig "$KUBECONFIG_OUT" >/dev/null
kubectl config use-context "$CONTEXT_NAME" --kubeconfig "$KUBECONFIG_OUT" >/dev/null

chmod 600 "$KUBECONFIG_OUT"

echo
echo "Done. ${SERVICEACCOUNT}'s kubeconfig: $KUBECONFIG_OUT"
echo "This token expires in ${DURATION} (or sooner, if the API server caps token lifetimes) --"
echo "there is nothing to revoke early beyond that: delete the ServiceAccount or its"
echo "RoleBinding to cut its access off immediately instead of waiting it out."
echo
echo "Test it with:"
echo "  kubectl --kubeconfig $KUBECONFIG_OUT auth whoami"
