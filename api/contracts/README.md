# API contracts

JSON Schemas (draft 2020-12) for every JSON endpoint. `api/tests/` validates real responses
against them, so a pipeline that runs the tests also catches contract breaks.

| Schema | Endpoint |
|---|---|
| `info.schema.json` | `GET /api/info` |
| `build.schema.json` | `GET /api/build` (the frontend's `/build.json` has the same shape) |
| `results.schema.json` | `GET /api/results` |
| `vote.schema.json` | `POST /api/vote` (200) |
| `error.schema.json` | any 4xx/5xx JSON error |
| `nodes.schema.json` | `GET /api/nodes` |
| `cluster-pods.schema.json` | `GET /api/cluster/pods` |
| `release-security.schema.json` | `GET /api/release/security` |
| `security-summary.schema.json` | the `security-summary.json` a pipeline produces, passed to the app as `RELEASE_SECURITY_SUMMARY` |

Rule: fields are only ever **added**. Removing or retyping a field is a breaking change.
