#!/usr/bin/env python3
"""security-report.py -- merge every scanner's output into ONE security summary.

Writes, into --out-dir:
  security-summary.json   compact counts (api/contracts/security-summary.schema.json). Small enough
                          to hand to the running app as RELEASE_SECURITY_SUMMARY (card 7).
  security-summary.md     for the GitHub job summary and a sticky PR comment
  security-summary.html   a standalone page for build artifacts / GitHub Releases

Every input is optional: a missing file shows the tool as "skipped" (e.g. SonarQube without a token).
Suppressed / accepted findings are COUNTED and shown, never silently dropped.

  scripts/security-report.py --out-dir reports \\
      --gitleaks reports/gitleaks.json --gitleaks-ignore .gitleaksignore \\
      --trufflehog reports/trufflehog.json \\
      --trivy fs=reports/trivy-fs.json --trivy config=reports/trivy-config.json \\
      --trivy image-api=reports/trivy-image-api.json \\
      --sarif zizmor=reports/zizmor.sarif \\
      --sonar-issues reports/sonar-issues.json --sonar-gate reports/sonar-gate.json \\
      --zap reports/zap.json

Input formats (what the tools write):
  gitleaks    --report-format json             (a JSON array of findings)
  trufflehog  --json                           (one JSON object per line; Verified true/false)
  trivy       --format json [--show-suppressed] (suppressed ones under ExperimentalModifiedFindings)
  sarif       any SARIF 2.1.0 (zizmor, hadolint, ...): level error/warning/note, `suppressions`
  sonar       GET /api/issues/search  and  GET /api/qualitygates/project_status responses
  zap         zap-baseline.py -J report.json

Gate (--fail-on, default critical,high): a tool FAILS if it has a non-suppressed finding at those
severities. Exceptions, matching how the scanners are meant to be gated:
  * trufflehog: only VERIFIED secrets fail (unverified ones are reported as medium)
  * gitleaks:   any finding fails (every leak matters; fix it or suppress it with a justification)
  * trivy:      vulnerabilities with no fixed version are counted but never fail (--ignore-unfixed)
  * sonar:      the quality gate status decides when --sonar-gate is given
Exit code is 0 unless --exit-code is set: the scanners gate the pipeline, this script REPORTS.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import pathlib
import sys

SEVERITIES = ["critical", "high", "medium", "low", "unknown"]
MARKER = "<!-- podpoll-security-summary -->"   # lets a workflow find and update its own PR comment


class Tool:
    def __init__(self, name: str, category: str):
        self.name = name
        self.category = category
        self.findings = {s: 0 for s in SEVERITIES}
        self.suppressed = 0
        self.unfixed = 0
        self.details: list[dict] = []
        self.status = "pass"
        self.note = ""

    def add(self, severity: str, rule: str, location: str, title: str, gating: bool = True) -> None:
        sev = severity if severity in SEVERITIES else "unknown"
        self.findings[sev] += 1
        self.details.append({"tool": self.name, "severity": sev, "rule": rule, "location": location,
                             "title": title, "gating": gating})

    def evaluate(self, fail_on: set[str]) -> None:
        if self.status == "skipped":
            return
        if any(d["gating"] and d["severity"] in fail_on for d in self.details):
            self.status = "fail"

    def to_json(self) -> dict:
        return {"name": self.name, "category": self.category, "status": self.status,
                "findings": dict(self.findings), "suppressed": self.suppressed}


def load_json(path: pathlib.Path):
    text = path.read_text(encoding="utf-8").strip()
    return json.loads(text) if text else None


def skipped(name: str, category: str, why: str) -> Tool:
    t = Tool(name, category)
    t.status, t.note = "skipped", why
    return t


# --- parsers ----------------------------------------------------------------------------------
def parse_gitleaks(path: pathlib.Path, ignore: pathlib.Path | None) -> Tool:
    t = Tool("gitleaks", "secrets")
    for f in load_json(path) or []:
        t.add("high", f.get("RuleID", "?"), f"{f.get('File', '?')}:{f.get('StartLine', '?')}",
              f.get("Description", "secret"))
    # gitleaks drops ignored findings from its report, so count the declared suppressions instead.
    if ignore and ignore.exists():
        lines = [x.strip() for x in ignore.read_text().splitlines()]
        t.suppressed = sum(1 for x in lines if x and not x.startswith("#"))
    return t


def parse_trufflehog(path: pathlib.Path) -> Tool:
    t = Tool("trufflehog", "secrets")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        r = json.loads(line)
        if "DetectorName" not in r:      # trufflehog also logs non-finding JSON lines
            continue
        data = (r.get("SourceMetadata") or {}).get("Data") or {}
        src = next(iter(data.values()), {}) if data else {}
        loc = f"{src.get('file', '?')}:{src.get('line', '?')}"
        if r.get("Verified"):
            t.add("critical", r["DetectorName"], loc, "VERIFIED live credential")
        else:
            t.add("medium", r["DetectorName"], loc, "unverified secret (could not be confirmed live)", gating=False)
    return t


TRIVY_CATEGORY = {"fs": "dependencies", "config": "iac"}


def parse_trivy(label: str, path: pathlib.Path) -> Tool:
    category = TRIVY_CATEGORY.get(label, "image" if label.startswith("image") else "other")
    t = Tool(f"trivy-{label}", category)
    report = load_json(path) or {}
    for res in report.get("Results") or []:
        target = res.get("Target", "?")
        for v in res.get("Vulnerabilities") or []:
            fixed = bool(v.get("FixedVersion"))
            if not fixed:
                t.unfixed += 1
            t.add(v.get("Severity", "UNKNOWN").lower(), v.get("VulnerabilityID", "?"),
                  f"{target} ({v.get('PkgName', '?')} {v.get('InstalledVersion', '')})",
                  (v.get("Title") or v.get("VulnerabilityID", "")) + ("" if fixed else " [no fix yet]"),
                  gating=fixed)
        for m in res.get("Misconfigurations") or []:
            if m.get("Status", "FAIL") != "FAIL":
                continue
            t.add(m.get("Severity", "UNKNOWN").lower(), m.get("ID", "?"), target, m.get("Title", ""))
        for s in res.get("Secrets") or []:
            t.add(s.get("Severity", "UNKNOWN").lower(), s.get("RuleID", "?"),
                  f"{target}:{s.get('StartLine', '?')}", s.get("Title", "secret"))
        t.suppressed += len(res.get("ExperimentalModifiedFindings") or res.get("ModifiedFindings") or [])
    return t


SARIF_LEVEL = {"error": "high", "warning": "medium", "note": "low", "none": "low"}


def parse_sarif(label: str, path: pathlib.Path) -> Tool:
    t = Tool(label, "pipeline" if label in ("zizmor", "actionlint") else "other")
    for run in (load_json(path) or {}).get("runs") or []:
        for r in run.get("results") or []:
            if r.get("suppressions"):
                t.suppressed += 1
                continue
            loc = "?"
            locs = r.get("locations") or []
            if locs:
                pl = locs[0].get("physicalLocation", {})
                loc = f"{pl.get('artifactLocation', {}).get('uri', '?')}:{pl.get('region', {}).get('startLine', '?')}"
            t.add(SARIF_LEVEL.get(r.get("level", "warning"), "unknown"), r.get("ruleId", "?"), loc,
                  (r.get("message") or {}).get("text", "")[:200])
    return t


SONAR_SEVERITY = {"BLOCKER": "critical", "HIGH": "high", "CRITICAL": "high", "MEDIUM": "medium",
                  "MAJOR": "medium", "LOW": "low", "MINOR": "low", "INFO": "low"}
SONAR_RANK = ["BLOCKER", "HIGH", "CRITICAL", "MEDIUM", "MAJOR", "LOW", "MINOR", "INFO"]


def parse_sonar(issues: pathlib.Path | None, gate: pathlib.Path | None) -> Tool:
    t = Tool("sonarqube", "sast")
    if issues:
        for i in (load_json(issues) or {}).get("issues") or []:
            # New "impacts" model (MQR mode) first; fall back to the legacy severity.
            sevs = [x.get("severity", "") for x in i.get("impacts") or []] or [i.get("severity", "")]
            worst = min(sevs, key=lambda s: SONAR_RANK.index(s) if s in SONAR_RANK else 99)
            loc = f"{i.get('component', '?').split(':', 1)[-1]}:{i.get('line', '?')}"
            accepted = (i.get("resolution") in ("FALSE-POSITIVE", "WONTFIX")
                        or i.get("issueStatus") in ("ACCEPTED", "FALSE_POSITIVE"))
            if accepted:
                t.suppressed += 1
                continue
            # With a quality gate, the GATE decides; individual issues are informational.
            t.add(SONAR_SEVERITY.get(worst, "unknown"), i.get("rule", "?"), loc, i.get("message", ""),
                  gating=gate is None)
    if gate:
        status = ((load_json(gate) or {}).get("projectStatus") or {}).get("status", "NONE")
        t.note = f"quality gate: {status}"
        if status == "ERROR":
            t.status = "fail"
    return t


ZAP_RISK = {"3": "high", "2": "medium", "1": "low", "0": "low"}


def parse_zap(path: pathlib.Path) -> Tool:
    t = Tool("zap-baseline", "dast")
    for site in (load_json(path) or {}).get("site") or []:
        for a in site.get("alerts") or []:
            count = len(a.get("instances") or []) or 1
            for _ in range(count):
                t.add(ZAP_RISK.get(str(a.get("riskcode", "")), "unknown"), f"zap-{a.get('pluginid', '?')}",
                      site.get("@name", "?"), a.get("name") or a.get("alert", ""))
    return t


# --- rendering ----------------------------------------------------------------------------------
def summarize(tools: list[Tool], fail_on: set[str], meta: dict) -> dict:
    for t in tools:
        t.evaluate(fail_on)
    totals = {s: sum(t.findings[s] for t in tools) for s in SEVERITIES}
    totals["suppressed"] = sum(t.suppressed for t in tools)
    summary = {
        "schema_version": 1,
        "generated_at": meta["generated_at"],
        "git_sha": meta["git_sha"],
        "version": meta["version"],
        "ref": meta["ref"],
        "status": "fail" if any(t.status == "fail" for t in tools) else "pass",
        "gate": ",".join(s.upper() for s in SEVERITIES if s in fail_on) + " (fixable)",
        "totals": totals,
        "tools": [t.to_json() for t in tools],
    }
    if meta.get("report_url"):
        summary["report_url"] = meta["report_url"]
    return summary


ICON = {"pass": "✅", "fail": "❌", "skipped": "⏭️"}


def top_findings(tools: list[Tool], limit: int) -> list[dict]:
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    all_ = [d for t in tools for d in t.details]
    return sorted(all_, key=lambda d: (rank[d["severity"]], not d["gating"], d["tool"]))[:limit]


def md_cell(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def render_md(summary: dict, tools: list[Tool], limit: int) -> str:
    t = summary["totals"]
    head = "✅ **PASS**" if summary["status"] == "pass" else "❌ **FAIL**"
    out = [MARKER, f"## 🛡️ Security summary: {head}", "",
           f"Commit `{summary['git_sha'][:7]}` · version `{summary['version']}` · gate: {summary['gate']} · "
           f"{t['suppressed']} finding(s) accepted as risk (suppressed with a justification)", "",
           "| Tool | Category | Critical | High | Medium | Low | Accepted | Result |",
           "|---|---|---:|---:|---:|---:|---:|---|"]
    for tool in tools:
        f = tool.findings
        result = f"{ICON[tool.status]} {tool.status}" + (f" ({tool.note})" if tool.note else "")
        extra = f" (+{tool.unfixed} no fix yet)" if tool.unfixed else ""
        out.append(f"| {tool.name} | {tool.category} | {f['critical']} | {f['high']} | {f['medium']} | "
                   f"{f['low']}{extra} | {tool.suppressed} | {md_cell(result)} |")
    findings = top_findings(tools, limit)
    if findings:
        out += ["", f"<details><summary>Top {len(findings)} findings</summary>", "",
                "| Severity | Tool | Rule | Location | Title |", "|---|---|---|---|---|"]
        for d in findings:
            sev = d["severity"] + ("" if d["gating"] else " (info)")
            out.append(f"| {sev} | {d['tool']} | `{md_cell(d['rule'])}` | `{md_cell(d['location'])}` | "
                       f"{md_cell(d['title'])[:120]} |")
        out += ["", "</details>"]
    if summary.get("report_url"):
        out += ["", f"[Full report]({summary['report_url']})"]
    return "\n".join(out) + "\n"


def render_html(summary: dict, tools: list[Tool], limit: int) -> str:
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(t.name)}</td><td>{e(t.category)}</td>"
        + "".join(f"<td class=n>{t.findings[s]}</td>" for s in ["critical", "high", "medium", "low"])
        + f"<td class=n>{t.suppressed}</td><td class={e(t.status)}>{e(t.status)}"
        + (f" · {e(t.note)}" if t.note else "") + "</td></tr>"
        for t in tools)
    finds = "".join(
        f"<tr><td class=sev-{e(d['severity'])}>{e(d['severity'])}{'' if d['gating'] else ' (info)'}</td>"
        f"<td>{e(d['tool'])}</td><td><code>{e(d['rule'])}</code></td><td><code>{e(d['location'])}</code></td>"
        f"<td>{e(d['title'])}</td></tr>" for d in top_findings(tools, limit))
    t = summary["totals"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>PodPoll security summary {e(summary['git_sha'][:7])}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font:14px/1.5 system-ui,sans-serif;margin:24px;background:#0f172a;color:#e2e8f0}}
table{{border-collapse:collapse;width:100%;margin:12px 0}}
th,td{{padding:6px 8px;border-bottom:1px solid #334155;text-align:left}}
th{{color:#94a3b8}}.n{{text-align:right}}.pass{{color:#4ade80}}.fail{{color:#f87171;font-weight:700}}.skipped{{color:#94a3b8}}
.sev-critical{{color:#fca5a5;font-weight:700}}.sev-high{{color:#fdba74}}code{{font-size:12px}}
.badge{{display:inline-block;padding:3px 12px;border-radius:999px;font-weight:700}}
.badge.pass{{background:#14532d;color:#bbf7d0}}.badge.fail{{background:#450a0a;color:#fecaca}}
</style></head><body>
<h1>Security summary <span class="badge {e(summary['status'])}">{e(summary['status'].upper())}</span></h1>
<p>Commit <code>{e(summary['git_sha'])}</code> · version <code>{e(summary['version'])}</code>
· ref <code>{e(summary['ref'])}</code>
· generated {e(summary['generated_at'])} · gate: {e(summary['gate'])} · {t['suppressed']} accepted as risk</p>
<table><tr><th>Tool</th><th>Category</th><th>Critical</th><th>High</th><th>Medium</th><th>Low</th><th>Accepted</th><th>Result</th></tr>{rows}</table>
<h2>Top findings</h2>
<table><tr><th>Severity</th><th>Tool</th><th>Rule</th><th>Location</th><th>Title</th></tr>
{finds or '<tr><td colspan=5>none</td></tr>'}</table>
</body></html>
"""


# --- CLI -------------------------------------------------------------------------------------------
def labelled(values: list[str]) -> list[tuple[str, pathlib.Path]]:
    out = []
    for v in values:
        label, sep, path = v.partition("=")
        if not sep:
            raise SystemExit(f"expected LABEL=PATH, got {v!r}")
        out.append((label, pathlib.Path(path)))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--out-dir", default="reports", type=pathlib.Path)
    p.add_argument("--gitleaks", type=pathlib.Path)
    p.add_argument("--gitleaks-ignore", type=pathlib.Path)
    p.add_argument("--trufflehog", type=pathlib.Path)
    p.add_argument("--trivy", action="append", default=[], metavar="LABEL=PATH",
                   help="fs=..., config=..., image-<name>=... (repeatable)")
    p.add_argument("--sarif", action="append", default=[], metavar="LABEL=PATH", help="e.g. zizmor=zizmor.sarif")
    p.add_argument("--sonar-issues", type=pathlib.Path)
    p.add_argument("--sonar-gate", type=pathlib.Path)
    p.add_argument("--zap", type=pathlib.Path)
    p.add_argument("--fail-on", default="critical,high")
    p.add_argument("--git-sha", default=os.getenv("GIT_SHA") or os.getenv("GITHUB_SHA") or "unknown")
    p.add_argument("--version", default=os.getenv("APP_VERSION", "unknown"))
    p.add_argument("--ref", default=os.getenv("GIT_REF") or os.getenv("GITHUB_REF") or "unknown")
    p.add_argument("--report-url", default="")
    p.add_argument("--max-findings", type=int, default=25)
    p.add_argument("--exit-code", action="store_true", help="exit 1 when the overall status is fail")
    a = p.parse_args(argv)

    fail_on = {s.strip().lower() for s in a.fail_on.split(",") if s.strip()}
    tools: list[Tool] = []

    def run(name, category, path, fn):
        if path is None:
            return
        if not path.exists():
            tools.append(skipped(name, category, "no report"))
            return
        try:
            tools.append(fn())
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            t = skipped(name, category, f"unreadable report: {e}")
            tools.append(t)

    run("gitleaks", "secrets", a.gitleaks, lambda: parse_gitleaks(a.gitleaks, a.gitleaks_ignore))
    run("trufflehog", "secrets", a.trufflehog, lambda: parse_trufflehog(a.trufflehog))
    for label, path in labelled(a.trivy):
        run(f"trivy-{label}", TRIVY_CATEGORY.get(label, "image"), path, lambda lb=label, pt=path: parse_trivy(lb, pt))
    for label, path in labelled(a.sarif):
        run(label, "pipeline", path, lambda lb=label, pt=path: parse_sarif(lb, pt))
    if a.sonar_issues is not None or a.sonar_gate is not None:
        missing = [x for x in (a.sonar_issues, a.sonar_gate) if x is not None and not x.exists()]
        if missing:
            tools.append(skipped("sonarqube", "sast", "no report (SONAR_TOKEN not set?)"))
        else:
            tools.append(parse_sonar(a.sonar_issues, a.sonar_gate))
    run("zap-baseline", "dast", a.zap, lambda: parse_zap(a.zap))

    meta = {"generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "git_sha": a.git_sha, "version": a.version, "ref": a.ref, "report_url": a.report_url}
    summary = summarize(tools, fail_on, meta)

    a.out_dir.mkdir(parents=True, exist_ok=True)
    (a.out_dir / "security-summary.json").write_text(json.dumps(summary, separators=(",", ":")) + "\n")
    (a.out_dir / "security-summary.md").write_text(render_md(summary, tools, a.max_findings))
    (a.out_dir / "security-summary.html").write_text(render_html(summary, tools, a.max_findings))

    print(f"security summary: {summary['status'].upper()}  "
          + "  ".join(f"{t.name}={t.status}" for t in tools) + f"  -> {a.out_dir}/security-summary.*")
    return 1 if a.exit_code and summary["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
