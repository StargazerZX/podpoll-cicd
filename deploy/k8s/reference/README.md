# Reference: push-based deploys from CI (the anti-pattern GitOps replaces)

Kept from the Kubernetes workshop for the optional comparison in Phase 5. **Not** applied by anything.

- `ci-deployer.yaml`: a least-privilege ServiceAccount + Role a pipeline could use to run
  `kubectl set image` / `rollout status` / `rollout undo` in one namespace.
- `make-sa-kubeconfig.sh`: mints a short-lived token for it and wraps it in a kubeconfig, which is
  what you would store as a CI secret.

Even scoped this tightly, the pipeline **holds cluster credentials** and **pushes** changes. With
Argo CD (Phase 5) the cluster **pulls** desired state from Git, and CI never touches the cluster at all.
