# Sample data for local demos

`security-summary.json` is a **made-up** example of the file a Phase 3 pipeline produces
(`scripts/security-report.py` → `security-summary.json`). The staging env file points the API at
it (`RELEASE_SECURITY_SUMMARY_FILE`), so card 7 "Release security" can be seen locally.
It validates against `api/contracts/security-summary.schema.json`.
