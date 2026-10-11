// Unit tests for frontend/logic.js.  Run:  node --test frontend/tests/
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("../logic.js");

test("envColour: fixed colours per environment, purple otherwise", () => {
  assert.equal(L.envColour("prod"), "#b91c1c");
  assert.equal(L.envColour("staging"), "#c2410c");
  assert.equal(L.envColour("dev"), "#15803d");
  assert.equal(L.envColour("preview"), "#0f766e");
  assert.equal(L.envColour("default"), "#1d4ed8");
  assert.equal(L.envColour("qa"), "#7e22ce");
  assert.equal(L.envColour(undefined), "#7e22ce");
});

test("majorOf: only the major version picks the theme", () => {
  assert.equal(L.majorOf("1.0"), "1");
  assert.equal(L.majorOf("2.3.1-abc123"), "2");
  assert.equal(L.majorOf("v3.0.0"), "3");
  assert.equal(L.majorOf("03.1"), "3");
  assert.equal(L.majorOf("dev"), "");
  assert.equal(L.majorOf(""), "");
  assert.equal(L.majorOf(null), "");
});

test("shortSha and isKnownSha", () => {
  assert.equal(L.shortSha("0123456789abcdef0123456789abcdef01234567"), "0123456");
  assert.equal(L.shortSha("unknown"), "unknown");
  assert.equal(L.shortSha("ABCDEF0"), "unknown");   // the API lowercases; uppercase means unsanitised
});

test("isMixedRelease: only when both commits are known and differ", () => {
  const a = "a".repeat(40), b = "b".repeat(40);
  assert.equal(L.isMixedRelease(a, b), true);
  assert.equal(L.isMixedRelease(a, a), false);
  assert.equal(L.isMixedRelease("unknown", b), false);
  assert.equal(L.isMixedRelease("unknown", "unknown"), false);
});

test("commitUrl and isSafeUrl reject anything that is not plain http(s)", () => {
  const sha = "c".repeat(40);
  assert.equal(L.commitUrl("https://github.com/u/r", sha), `https://github.com/u/r/commit/${sha}`);
  assert.equal(L.commitUrl("", sha), "");
  assert.equal(L.commitUrl("https://github.com/u/r", "unknown"), "");
  assert.equal(L.isSafeUrl("javascript:alert(1)"), false);
  assert.equal(L.isSafeUrl('https://x/"onmouseover=1'), false);
  assert.equal(L.isSafeUrl("https://ci.example/run?id=1&x=2"), true);
});

test("ageText", () => {
  const now = Date.parse("2026-10-11T10:00:00Z");
  assert.equal(L.ageText("2026-10-11T09:59:58Z", now), "just now");
  assert.equal(L.ageText("2026-10-11T09:59:00Z", now), "60 s ago");
  assert.equal(L.ageText("2026-10-11T09:55:00Z", now), "5 min ago");
  assert.equal(L.ageText("2026-10-11T07:00:00Z", now), "3 h ago");
  assert.equal(L.ageText("2026-10-08T10:00:00Z", now), "3 days ago");
  assert.equal(L.ageText("2026-10-11T11:00:00Z", now), "in the future?");
  assert.equal(L.ageText("unknown", now), "unknown");
});

test("chaosSummary", () => {
  assert.equal(L.chaosSummary(null), "");
  assert.equal(L.chaosSummary({ ready_fail: false, start_delay_seconds: 0, error_rate: 0 }), "");
  assert.equal(L.chaosSummary({ ready_fail: true, start_delay_seconds: 20, error_rate: 0.2 }),
               "readiness failing, slow start 20s, 20% vote errors");
});

test("every platform defines every hint key", () => {
  const keys = Object.keys(L.HINTS.docker).sort();
  for (const p of ["kubernetes", "ecs", "docker"]) {
    assert.deepEqual(Object.keys(L.hintsFor(p)).sort(), keys, p);
    assert.ok(L.hintsFor(p).debug.length > 0);
  }
  assert.equal(L.hintsFor("mainframe"), null);
  assert.ok(!JSON.stringify(L.HINTS).includes("Module"), "no k8s-workshop module references");
});

test("Kubernetes-only wording stays on Kubernetes", () => {
  assert.equal(L.hintsFor("kubernetes").envLabel, "namespace");
  assert.equal(L.hintsFor("ecs").nodesTitle, "Tasks (each task is its own micro-VM)");
  assert.equal(L.hintsFor("docker").nodesTitle, "Host");
  for (const p of ["ecs", "docker"]) assert.ok(!L.hintsFor(p).debug.join(" ").includes("kubectl"));
});
