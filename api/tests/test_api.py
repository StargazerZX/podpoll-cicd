"""Endpoint tests in Redis mode (fakeredis). Shapes are checked against api/contracts/."""
import json

import fakeredis
import pytest
from conftest import assert_contract


def broken_redis():
    server = fakeredis.FakeServer()
    server.connected = False  # every command raises redis.ConnectionError
    return fakeredis.FakeRedis(server=server, decode_responses=True)


# --- health ------------------------------------------------------------------
def test_healthz_is_always_ok(api):
    mod, client = api
    mod.r = broken_redis()  # liveness must NOT depend on the store
    res = client.get("/healthz")
    assert res.status_code == 200 and res.text == "ok\n"


def test_readyz_follows_the_store(api):
    mod, client = api
    assert client.get("/readyz").status_code == 200
    mod.r = broken_redis()
    res = client.get("/readyz")
    assert res.status_code == 503 and "store unreachable" in res.text


# --- info --------------------------------------------------------------------
def test_info_keeps_original_fields_and_adds_new_ones(load_app):
    mod = load_app(POD_NAME="api-1", POD_NAMESPACE="dev", NODE_NAME="node-a", APP_VERSION="2.0",
                   GIT_SHA="0123456789abcdef0123456789abcdef01234567", CI_SYSTEM="github-actions")
    d = mod.app.test_client().get("/api/info").get_json()
    assert_contract("info", d)
    assert d["pod"] == "api-1" and d["namespace"] == "dev" and d["node"] == "node-a"
    assert d["version"] == "2.0" and d["store"] == "redis" and d["db_host"] == "redis"
    assert d["db_server"] == "api-1" and d["db_ok"] is True    # the Redis-mode quirk is preserved
    assert d["env"] == "dev"                                   # falls back to POD_NAMESPACE
    assert d["git_sha"].startswith("0123456") and d["ci_system"] == "github-actions"
    assert d["platform"] == "docker" and d["task"] is None and d["reset_protected"] is False
    assert d["chaos"] == {"ready_fail": False, "start_delay_seconds": 0, "error_rate": 0}


def test_podpoll_env_wins_over_namespace(load_app):
    mod = load_app(POD_NAMESPACE="team-a", PODPOLL_ENV="staging")
    d = mod.app.test_client().get("/api/info").get_json()
    assert d["env"] == "staging" and d["namespace"] == "team-a"


def test_info_defaults_outside_kubernetes(load_app):
    d = load_app().app.test_client().get("/api/info").get_json()
    assert d["namespace"] == "unknown" and d["env"] == "unknown" and d["node"] == "unknown"
    assert d["version"] == "dev"


# --- platform detection ------------------------------------------------------
@pytest.mark.parametrize("env,expected", [
    ({}, "docker"),
    ({"KUBERNETES_SERVICE_HOST": "10.96.0.1"}, "kubernetes"),
    ({"ECS_CONTAINER_METADATA_URI_V4": "http://169.254.170.2/v4/abc"}, "ecs"),
    ({"PLATFORM": "ECS", "KUBERNETES_SERVICE_HOST": "10.96.0.1"}, "ecs"),   # explicit wins
    ({"PLATFORM": "bogus"}, "docker"),                                       # invalid -> auto
    ({"PLATFORM": ""}, "docker"),
])
def test_detect_platform(load_app, env, expected):
    assert load_app().detect_platform(env) == expected


ECS_TASK = {
    "Cluster": "arn:aws:ecs:eu-central-1:111122223333:cluster/podpoll",
    "TaskARN": "arn:aws:ecs:eu-central-1:111122223333:task/podpoll/0f1e2d3c4b5a69788796a5b4c3d2e1f0",
    "Family": "podpoll-dev-api", "Revision": "7",
    "AvailabilityZone": "eu-central-1b", "LaunchType": "FARGATE",
}


def test_ecs_identity_comes_from_task_metadata(load_app, json_server):
    base = json_server({"/v4/abc/task": ECS_TASK}) + "/v4/abc"
    mod = load_app(ECS_CONTAINER_METADATA_URI_V4=base, PODPOLL_ENV="dev")
    d = mod.app.test_client().get("/api/info").get_json()
    assert_contract("info", d)
    assert d["platform"] == "ecs"
    assert d["pod"] == "0f1e2d3c4b5a69788796a5b4c3d2e1f0"
    assert d["node"] == "eu-central-1b / FARGATE"
    assert d["task"] == {"task_id": "0f1e2d3c4b5a69788796a5b4c3d2e1f0", "cluster": "podpoll",
                         "family": "podpoll-dev-api", "revision": "7",
                         "az": "eu-central-1b", "launch_type": "FARGATE"}


def test_ecs_explicit_names_still_win(load_app, json_server):
    base = json_server({"/v4/abc/task": ECS_TASK}) + "/v4/abc"
    mod = load_app(ECS_CONTAINER_METADATA_URI_V4=base, POD_NAME="me", NODE_NAME="here")
    assert (mod.POD_NAME, mod.NODE_NAME) == ("me", "here")


def test_unreachable_ecs_metadata_never_crashes(load_app):
    mod = load_app(ECS_CONTAINER_METADATA_URI_V4="http://127.0.0.1:9/v4/none")
    assert mod.PLATFORM == "ecs" and mod.ECS_TASK == {}
    assert mod.NODE_NAME == "unknown"
    assert mod.app.test_client().get("/healthz").status_code == 200


def test_ecs_metadata_ignored_off_ecs(load_app, json_server):
    base = json_server({"/v4/abc/task": ECS_TASK}) + "/v4/abc"
    mod = load_app(ECS_CONTAINER_METADATA_URI_V4=base, PLATFORM="docker")
    assert mod.ECS_TASK == {}


# --- build provenance --------------------------------------------------------
def test_build_defaults(api):
    _, client = api
    d = client.get("/api/build").get_json()
    assert_contract("build", d)
    assert d == {"version": "dev", "git_sha": "unknown", "git_sha_short": "unknown", "git_ref": "unknown",
                 "build_id": "local", "build_url": "", "ci_system": "local", "build_time": "unknown",
                 "source_url": "", "commit_url": ""}


def test_build_from_ci(load_app):
    sha = "abcdef0123456789abcdef0123456789abcdef01"
    mod = load_app(APP_VERSION="1.4.0", GIT_SHA=sha.upper(), GIT_REF="refs/heads/main", BUILD_ID="42",
                   BUILD_URL="https://github.com/u/podpoll-cicd/actions/runs/42", CI_SYSTEM="github-actions",
                   BUILD_TIME="2026-10-11T09:30:00Z", SOURCE_URL="https://github.com/u/podpoll-cicd")
    d = mod.app.test_client().get("/api/build").get_json()
    assert_contract("build", d)
    assert d["git_sha"] == sha and d["git_sha_short"] == "abcdef0"
    assert d["commit_url"] == f"https://github.com/u/podpoll-cicd/commit/{sha}"
    assert d["build_time"] == "2026-10-11T09:30:00Z" and d["build_id"] == "42"


@pytest.mark.parametrize("raw,expected", [
    ("2.3.1-abc123", "2.3.1-abc123"),
    ("feature/login", "feature-login"),          # a branch name with "/" used to break sed
    ("1.0 ; rm -rf /", "1.0---rm--rf--"),
    ("v1.2.3+build.7", "v1.2.3+build.7"),
    ("", "dev"),
])
def test_app_version_is_sanitised(load_app, raw, expected):
    assert load_app(APP_VERSION=raw).APP_VERSION == expected


def test_untrusted_build_values_are_dropped(load_app):
    mod = load_app(GIT_SHA="not-a-sha", BUILD_URL='https://x/"><script>', SOURCE_URL="javascript:alert(1)",
                   BUILD_TIME="yesterday", BUILD_ID="12 34", CI_SYSTEM="Jenkins!")
    d = mod.BUILD
    assert d["git_sha"] == "unknown" and d["build_url"] == "" and d["source_url"] == ""
    assert d["build_time"] == "unknown" and d["build_id"] == "12-34" and d["ci_system"] == "-enkins-"
    assert d["commit_url"] == ""


# --- poll --------------------------------------------------------------------
def test_results_zero_filled_with_default_question(api):
    _, client = api
    d = client.get("/api/results").get_json()
    assert_contract("results", d)
    assert [x["option"] for x in d["results"]] == ["Secret scan", "Unit tests", "SAST",
                                                  "Dependency scan", "Image scan", "Code review"]
    assert d["total"] == 0 and d["question"] == "Which pipeline gate saves you most often?"


def test_vote_and_count(api):
    _, client = api
    for _ in range(3):
        res = client.post("/api/vote", json={"option": "SAST"})
        assert res.status_code == 200
        assert_contract("vote", res.get_json())
    client.post("/api/vote", json={"option": "Image scan"})
    d = client.get("/api/results").get_json()
    counts = {x["option"]: x["votes"] for x in d["results"]}
    assert counts["SAST"] == 3 and counts["Image scan"] == 1 and d["total"] == 4


@pytest.mark.parametrize("body", [{"option": "Pod"}, {}, None, {"option": 1}])
def test_vote_rejects_unknown_option(api, body):
    _, client = api
    res = client.post("/api/vote", json=body) if body is not None else client.post("/api/vote", data="x")
    assert res.status_code == 400
    assert_contract("error", res.get_json())


def test_custom_poll(load_app):
    mod = load_app(POLL_QUESTION="Tabs or spaces?", POLL_OPTIONS=" Tabs , Spaces,,Tabs ")
    client = mod.app.test_client()
    d = client.get("/api/results").get_json()
    assert d["question"] == "Tabs or spaces?" and [x["option"] for x in d["results"]] == ["Tabs", "Spaces"]
    assert client.post("/api/vote", json={"option": "SAST"}).status_code == 400


@pytest.mark.parametrize("raw", ["", "only-one", " , ,"])
def test_too_few_options_fall_back_to_defaults(load_app, raw):
    mod = load_app()
    assert mod.parse_options(raw) == mod.DEFAULT_OPTIONS


def test_options_are_capped(load_app):
    mod = load_app()
    opts = mod.parse_options(",".join(f"o{i}" for i in range(20)) + "," + "x" * 99)
    assert len(opts) == 12 and all(len(o) <= 40 for o in opts)


# --- reset -------------------------------------------------------------------
def test_reset_is_open_by_default(api):
    _, client = api
    client.post("/api/vote", json={"option": "SAST"})
    assert client.post("/api/reset").get_json() == {"ok": True}
    assert client.get("/api/results").get_json()["total"] == 0


def test_reset_token(load_app):
    mod = load_app(RESET_TOKEN="s3cr3t-for-tests")
    client = mod.app.test_client()
    client.post("/api/vote", json={"option": "SAST"})
    assert client.get("/api/info").get_json()["reset_protected"] is True
    assert client.post("/api/reset").status_code == 403
    assert client.post("/api/reset", headers={"X-Reset-Token": "wrong"}).status_code == 403
    assert client.get("/api/results").get_json()["total"] == 1
    res = client.post("/api/reset", headers={"X-Reset-Token": "s3cr3t-for-tests"})
    assert res.status_code == 200 and client.get("/api/results").get_json()["total"] == 0


# --- store failures ----------------------------------------------------------
@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/results", None),
    ("post", "/api/vote", {"option": "SAST"}),
    ("post", "/api/reset", None),
    ("post", "/api/nodes/heartbeat", {"node": "n1"}),
    ("get", "/api/nodes", None),
])
def test_redis_down_gives_503(api, method, path, body):
    mod, client = api
    mod.r = broken_redis()
    res = getattr(client, method)(path, json=body)
    assert res.status_code == 503
    assert res.get_json()["error"] == "database unavailable"


# --- nodes -------------------------------------------------------------------
def test_heartbeat_requires_node(api):
    _, client = api
    res = client.post("/api/nodes/heartbeat", json={"kernel": "6.x"})
    assert res.status_code == 400


def test_heartbeats_listed_with_age_and_ttl(load_app):
    mod = load_app(NODE_TTL_SECONDS="45")
    client = mod.app.test_client()
    for n in ("node-b", "node-a"):
        res = client.post("/api/nodes/heartbeat", json={"node": n, "agent_pod": f"agent-{n}"})
        assert res.get_json() == {"ok": True}
    d = client.get("/api/nodes").get_json()
    assert_contract("nodes", d)
    assert [x["node"] for x in d["nodes"]] == ["node-a", "node-b"]
    assert all(x["age_seconds"] == 0 for x in d["nodes"])
    assert 0 < mod.r.ttl("node:node-a") <= 45


def test_heartbeat_expiring_between_scan_and_get(api, monkeypatch):
    mod, client = api
    client.post("/api/nodes/heartbeat", json={"node": "gone"})
    monkeypatch.setattr(mod.r, "get", lambda key: None)
    assert client.get("/api/nodes").get_json() == {"nodes": []}


# --- chaos -------------------------------------------------------------------
def test_chaos_ready_fail(load_app):
    client = load_app(CHAOS_READY_FAIL="true").app.test_client()
    res = client.get("/readyz")
    assert res.status_code == 503 and "CHAOS_READY_FAIL" in res.text
    assert client.get("/healthz").status_code == 200       # liveness ignores chaos
    assert client.get("/api/info").get_json()["chaos"]["ready_fail"] is True


def test_chaos_error_rate(load_app):
    client = load_app(CHAOS_ERROR_RATE="1").app.test_client()
    res = client.post("/api/vote", json={"option": "SAST"})
    assert res.status_code == 500 and "chaos" in res.get_json()["error"]
    assert client.post("/api/vote", json={"option": "nope"}).status_code == 400   # validation first
    assert client.get("/healthz").status_code == 200


def test_chaos_error_rate_partial(load_app, monkeypatch):
    mod = load_app(CHAOS_ERROR_RATE="0.2")
    client = mod.app.test_client()
    monkeypatch.setattr(mod.random, "random", lambda: 0.5)
    assert client.post("/api/vote", json={"option": "SAST"}).status_code == 200
    monkeypatch.setattr(mod.random, "random", lambda: 0.1)
    assert client.post("/api/vote", json={"option": "SAST"}).status_code == 500


@pytest.mark.parametrize("raw,expected", [("0.2", 0.2), ("5", 1.0), ("-1", 0.0), ("lots", 0.0)])
def test_chaos_error_rate_is_clamped(load_app, raw, expected):
    assert load_app(CHAOS_ERROR_RATE=raw).CHAOS_ERROR_RATE == expected


def test_chaos_start_delay(load_app, monkeypatch):
    mod = load_app(CHAOS_START_DELAY_SECONDS="12")
    slept = []
    monkeypatch.setattr(mod.time, "sleep", slept.append)
    mod.startup_delay()
    assert slept == [12.0]


def test_no_start_delay_by_default(load_app, monkeypatch):
    mod = load_app()
    monkeypatch.setattr(mod.time, "sleep", lambda s: pytest.fail("should not sleep"))
    mod.startup_delay()


def test_all_chaos_flags_leave_healthz_alone(load_app):
    client = load_app(CHAOS_READY_FAIL="1", CHAOS_ERROR_RATE="1").app.test_client()
    assert client.get("/healthz").status_code == 200


# --- release security --------------------------------------------------------
SUMMARY = {
    "schema_version": 1, "generated_at": "2026-10-11T10:00:00Z", "git_sha": "abc1234", "version": "1.4.0",
    "status": "pass", "gate": "CRITICAL,HIGH (fixable)",
    "totals": {"critical": 0, "high": 0, "medium": 2, "low": 5, "unknown": 0, "suppressed": 1},
    "tools": [{"name": "trivy-image", "category": "image", "status": "pass",
               "findings": {"critical": 0, "high": 0, "medium": 2, "low": 5, "unknown": 0}, "suppressed": 1}],
}


def test_release_security_absent(api):
    _, client = api
    d = client.get("/api/release/security").get_json()
    assert_contract("release-security", d)
    assert d == {"available": False}


def test_release_security_from_env(load_app):
    client = load_app(RELEASE_SECURITY_SUMMARY=json.dumps(SUMMARY)).app.test_client()
    d = client.get("/api/release/security").get_json()
    assert_contract("release-security", d)
    assert d["available"] is True and d["summary"]["totals"]["suppressed"] == 1


def test_release_security_from_file(load_app, tmp_path):
    f = tmp_path / "summary.json"
    f.write_text(json.dumps(SUMMARY))
    client = load_app(RELEASE_SECURITY_SUMMARY_FILE=str(f)).app.test_client()
    assert client.get("/api/release/security").get_json()["available"] is True


@pytest.mark.parametrize("env", [
    {"RELEASE_SECURITY_SUMMARY": "{not json"},
    {"RELEASE_SECURITY_SUMMARY": "[1, 2]"},
    {"RELEASE_SECURITY_SUMMARY_FILE": "/does/not/exist.json"},
])
def test_release_security_bad_input_is_hidden(load_app, env):
    d = load_app(**env).app.test_client().get("/api/release/security").get_json()
    assert d["available"] is False
