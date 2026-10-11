"""GET /api/cluster/pods -- the Kubernetes RBAC card, with the API server faked."""
import base64
import io
import json
import urllib.error

import pytest
from conftest import assert_contract


def make_token(sub="system:serviceaccount:dev:podpoll-api"):
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.sig"


@pytest.fixture
def sa_dir(tmp_path):
    d = tmp_path / "sa"
    d.mkdir()
    (d / "token").write_text(make_token() + "\n")
    (d / "namespace").write_text("dev\n")
    return d


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_no_token_mounted(api):
    _, client = api
    d = client.get("/api/cluster/pods").get_json()
    assert_contract("cluster-pods", d)
    assert d["allowed"] is False and d["status"] is None
    assert d["message"] == "No ServiceAccount token mounted (automountServiceAccountToken: false?)"


def test_allowed_lists_pods(load_app, sa_dir, monkeypatch):
    mod = load_app(SA_DIR=str(sa_dir), KUBERNETES_SERVICE_HOST="10.96.0.1", KUBERNETES_SERVICE_PORT="443")
    seen = {}
    pods = {"items": [{"metadata": {"name": "api-1"}, "spec": {"nodeName": "n1"},
                       "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}},
                      {"metadata": {"name": "redis-1"}, "status": {}}]}

    def fake_urlopen(req, timeout, context):
        seen["url"] = req.full_url
        seen["auth"] = req.headers["Authorization"]
        return FakeResponse(json.dumps(pods).encode())

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    d = mod.app.test_client().get("/api/cluster/pods").get_json()
    assert_contract("cluster-pods", d)
    assert seen["url"] == "https://10.96.0.1:443/api/v1/namespaces/dev/pods?labelSelector=part-of%3Dpodpoll"
    assert seen["auth"].startswith("Bearer eyJ")
    assert d["allowed"] is True and d["identity"] == "system:serviceaccount:dev:podpoll-api"
    assert d["pods"] == [{"name": "api-1", "phase": "Running", "node": "n1", "ready": "True"},
                         {"name": "redis-1", "phase": "Unknown", "node": "unknown", "ready": "Unknown"}]


def test_forbidden_passes_message_through(load_app, sa_dir, monkeypatch):
    mod = load_app(SA_DIR=str(sa_dir))
    status = {"kind": "Status", "message": 'pods is forbidden: User "x" cannot list resource "pods"'}

    def fake_urlopen(req, timeout, context):
        assert req.full_url.startswith("https://kubernetes.default.svc/")
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(json.dumps(status).encode()))

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    d = mod.app.test_client().get("/api/cluster/pods").get_json()
    assert d["allowed"] is False and d["status"] == 403 and d["message"] == status["message"]


def test_http_error_without_json_body(load_app, sa_dir, monkeypatch):
    mod = load_app(SA_DIR=str(sa_dir))

    def fake_urlopen(req, timeout, context):
        raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, io.BytesIO(b"<html>"))

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    d = mod.app.test_client().get("/api/cluster/pods").get_json()
    assert d["status"] == 500 and "boom" in d["message"]


def test_unreachable_api_server(load_app, sa_dir, monkeypatch):
    mod = load_app(SA_DIR=str(sa_dir))

    def fake_urlopen(req, timeout, context):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    d = mod.app.test_client().get("/api/cluster/pods").get_json()
    assert d["status"] is None and d["message"].startswith("could not reach the API server")


def test_ipv6_api_server_is_bracketed(load_app, monkeypatch):
    mod = load_app()
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "fd00::1")
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT", "6443")
    assert mod._apiserver_base_url() == "https://[fd00::1]:6443"


def test_jwt_sub_decoding(load_app):
    mod = load_app()
    assert mod._decode_jwt_sub(make_token("system:serviceaccount:a:b")) == "system:serviceaccount:a:b"
    assert mod._decode_jwt_sub("garbage") == "unknown"
