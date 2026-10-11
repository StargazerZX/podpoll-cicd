# security/: your scanner configuration lives here

Empty on purpose. In Phases 2 and 3 you add, with a justification for every exception:

| File | Phase | Purpose |
|---|---|---|
| `.gitleaks.toml` (repo root) | 2 | Gitleaks rules and allowlists |
| `.gitleaksignore` (repo root) | 2 | fingerprints of findings judged false positives |
| `security/trivy.yaml` | 3 | Trivy settings: severities, scanners, `ignore-unfixed` |
| `.trivyignore.yaml` (repo root) | 3 | accepted risks, each with a `statement` and an `expired_at` date |

Rule of thumb, which you'll practise in Phase 2: **never** silence a scanner by disabling a rule.
Suppress the single finding, say why, and give it an expiry date if it's a risk you're accepting.
