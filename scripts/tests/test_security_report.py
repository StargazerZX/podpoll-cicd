"""Tests for scripts/security-report.py, fed with REAL scanner output (fixtures/, captured 2026-10-11
from gitleaks 8.30.1, trufflehog 3.99.2, trivy 0.74.0, zizmor 1.30.1; secrets scrubbed). The
SonarQube and ZAP fixtures are hand-written from the documented formats.  Run: pytest scripts/tests"""
import importlib.util
import json
import pathlib

import pytest
from jsonschema import Draft202012Validator

HERE = pathlib.Path(__file__).resolve().parent
FIX = HERE / "fixtures"
ROOT = HERE.parents[1]
SCHEMA = json.loads((ROOT / "api/contracts/security-summary.schema.json").read_text())

spec = importlib.util.spec_from_file_location("security_report", ROOT / "scripts/security-report.py")
sr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sr)


def run(tmp_path, *args):
    code = sr.main(["--out-dir", str(tmp_path), "--git-sha", "0123456789abcdef0123456789abcdef01234567",
                    "--version", "1.2.3", "--ref", "refs/heads/main", *args])
    summary = json.loads((tmp_path / "security-summary.json").read_text())
    md = (tmp_path / "security-summary.md").read_text()
    html = (tmp_path / "security-summary.html").read_text()
    return code, summary, md, html


def tools_by_name(summary):
    return {t["name"]: t for t in summary["tools"]}


ALL = ["--gitleaks", str(FIX / "gitleaks.json"), "--gitleaks-ignore", str(FIX / "gitleaksignore"),
       "--trufflehog", str(FIX / "trufflehog.jsonl"),
       "--trivy", f"fs={FIX / 'trivy-fs.json'}", "--trivy", f"config={FIX / 'trivy-config.json'}",
       "--trivy", f"image-frontend={FIX / 'trivy-image.json'}",
       "--sarif", f"zizmor={FIX / 'zizmor.sarif'}",
       "--sonar-issues", str(FIX / "sonar-issues.json"), "--sonar-gate", str(FIX / "sonar-gate-error.json"),
       "--zap", str(FIX / "zap.json")]


def test_full_report_from_real_scanner_output(tmp_path):
    code, s, md, html = run(tmp_path, *ALL)
    assert code == 0                                   # reporting, not gating, by default
    Draft202012Validator(SCHEMA).validate(s)           # exactly what card 7 / the API contract expects
    t = tools_by_name(s)
    assert s["status"] == "fail" and s["gate"] == "CRITICAL,HIGH (fixable)"

    assert t["gitleaks"]["status"] == "fail" and t["gitleaks"]["findings"]["high"] == 2
    assert t["gitleaks"]["suppressed"] == 1            # declared in the ignore file
    assert t["trufflehog"]["status"] == "pass"         # unverified secrets are reported, not gated
    assert t["trufflehog"]["findings"]["medium"] == 2
    assert t["trivy-fs"]["status"] == "fail"           # requests CVE-2018-18074 (HIGH, fixed) + a secret
    assert t["trivy-fs"]["suppressed"] == 2            # one CVE + one secret in .trivyignore.yaml
    assert t["trivy-fs"]["category"] == "dependencies"
    assert t["trivy-config"]["status"] == "fail" and t["trivy-config"]["findings"]["high"] == 1   # DS-0002
    assert t["trivy-image-frontend"]["category"] == "image"
    assert t["zizmor"]["status"] == "fail" and t["zizmor"]["findings"]["high"] == 3
    assert t["sonarqube"]["status"] == "fail" and t["sonarqube"]["suppressed"] == 1   # gate ERROR; 1 accepted
    assert t["zap-baseline"]["status"] == "pass" and t["zap-baseline"]["findings"]["medium"] == 2
    assert s["totals"]["suppressed"] == sum(x["suppressed"] for x in s["tools"])

    assert md.startswith(sr.MARKER) and "❌ **FAIL**" in md and "quality gate: ERROR" in md
    assert "accepted as risk" in md and "CVE-2018-18074" in md
    assert "<h1>Security summary" in html


def test_summary_is_small_enough_for_an_ecs_env_var(tmp_path):
    _, _, _, _ = run(tmp_path, *ALL)
    assert len((tmp_path / "security-summary.json").read_bytes()) < 4096


def test_missing_reports_are_skipped_not_failed(tmp_path):
    code, s, md, _ = run(tmp_path, "--gitleaks", str(tmp_path / "nope.json"),
                         "--sonar-issues", str(tmp_path / "nope.json"))
    t = tools_by_name(s)
    assert s["status"] == "pass" and code == 0
    assert t["gitleaks"]["status"] == "skipped" and t["sonarqube"]["status"] == "skipped"
    assert "SONAR_TOKEN" in md
    Draft202012Validator(SCHEMA).validate(s)


def test_no_inputs_at_all(tmp_path):
    _, s, _, _ = run(tmp_path)
    assert s["status"] == "pass" and s["tools"] == []
    Draft202012Validator(SCHEMA).validate(s)


def test_verified_secret_fails_and_log_lines_are_ignored(tmp_path):
    _, s, md, _ = run(tmp_path, "--trufflehog", str(FIX / "trufflehog-verified.jsonl"))
    t = tools_by_name(s)["trufflehog"]
    assert t["status"] == "fail" and t["findings"]["critical"] == 1 and sum(t["findings"].values()) == 1
    assert "VERIFIED" in md


def test_unfixed_vulnerabilities_are_counted_but_do_not_gate(tmp_path):
    report = {"Results": [{"Target": "img", "Vulnerabilities": [
        {"VulnerabilityID": "CVE-2026-0001", "PkgName": "libfoo", "InstalledVersion": "1.0",
         "FixedVersion": "", "Severity": "CRITICAL", "Title": "no fix yet"}]}]}
    f = tmp_path / "t.json"
    f.write_text(json.dumps(report))
    _, s, md, _ = run(tmp_path, "--trivy", f"image-api={f}")
    t = tools_by_name(s)["trivy-image-api"]
    assert t["status"] == "pass" and t["findings"]["critical"] == 1
    assert "+1 no fix yet" in md and "(info)" in md


def test_sonar_without_gate_gates_on_severity(tmp_path):
    _, s, _, _ = run(tmp_path, "--sonar-issues", str(FIX / "sonar-issues.json"))
    t = tools_by_name(s)["sonarqube"]
    assert t["status"] == "fail" and t["findings"]["critical"] == 1   # BLOCKER


def test_custom_fail_on(tmp_path):
    _, s, _, _ = run(tmp_path, "--zap", str(FIX / "zap.json"), "--fail-on", "critical,high,medium")
    assert tools_by_name(s)["zap-baseline"]["status"] == "fail"
    assert s["gate"] == "CRITICAL,HIGH,MEDIUM (fixable)"


def test_exit_code_flag(tmp_path):
    code, _, _, _ = run(tmp_path, "--exit-code", "--gitleaks", str(FIX / "gitleaks.json"))
    assert code == 1


def test_untrusted_text_is_escaped(tmp_path):
    report = {"runs": [{"results": [{"ruleId": "x|y", "level": "error",
                                     "message": {"text": "<script>alert(1)</script> | pipe"}}]}]}
    f = tmp_path / "evil.sarif"
    f.write_text(json.dumps(report))
    _, _, md, html = run(tmp_path, "--sarif", f"zizmor={f}")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "x\\|y" in md and "\\| pipe" in md


def test_unreadable_report_is_skipped(tmp_path):
    f = tmp_path / "broken.json"
    f.write_text("{not json")
    _, s, _, _ = run(tmp_path, "--trivy", f"fs={f}")
    t = tools_by_name(s)["trivy-fs"]
    assert t["status"] == "skipped"


def test_label_syntax_is_enforced(tmp_path):
    with pytest.raises(SystemExit):
        sr.main(["--out-dir", str(tmp_path), "--trivy", "no-equals-sign.json"])


def test_local_sample_matches_the_contract():
    sample = json.loads((ROOT / "local/sample/security-summary.json").read_text())
    Draft202012Validator(SCHEMA).validate(sample)
