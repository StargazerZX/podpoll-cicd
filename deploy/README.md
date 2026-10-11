# deploy/

| Path | Who writes it | What |
|---|---|---|
| `k8s/base/` | provided | Kustomize base: redis, api (+ ServiceAccount/Role/RoleBinding), frontend, node-agent. No namespace, placeholder images |
| `k8s/overlays/<env>/` | **you, Phase 5** | namespace, image digests, `PODPOLL_ENV`, replicas, security-summary ConfigMap |
| `argocd/` | **you, Phase 5** | AppProject + Applications |
| `ecs/` | **you, Phase 4** | ECS task definitions |
| `k8s/reference/` | provided | the push-based CI deployer, for comparison |

Check the base renders and is valid:

```bash
kubectl kustomize deploy/k8s/base            # or: kustomize build deploy/k8s/base
```
