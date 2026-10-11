"""Shared fixtures.

app.py reads its configuration from env vars at IMPORT time (12-factor style), so every test
that needs a different configuration re-imports the module with a fresh environment.
Redis is replaced by fakeredis; Postgres tests (marker `pg`) need a real server, see test_postgres.py.
"""
import importlib
import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import fakeredis
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

API_DIR = pathlib.Path(__file__).resolve().parents[1]
CONTRACTS = API_DIR / "contracts"
sys.path.insert(0, str(API_DIR))

# Every variable app.py reads -- cleared before each load so the developer's shell can't leak in.
APP_ENV_VARS = [
    "REDIS_HOST", "REDIS_TCP_PORT", "POD_NAME", "POD_NAMESPACE", "NODE_NAME", "APP_VERSION",
    "NODE_TTL_SECONDS", "PODPOLL_ENV", "PLATFORM", "KUBERNETES_SERVICE_HOST", "KUBERNETES_SERVICE_PORT",
    "ECS_CONTAINER_METADATA_URI_V4", "DB_HOST", "DB_TCP_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
    "SA_DIR", "GIT_SHA", "GIT_REF", "BUILD_ID", "BUILD_URL", "CI_SYSTEM", "BUILD_TIME", "SOURCE_URL",
    "POLL_QUESTION", "POLL_OPTIONS", "CHAOS_READY_FAIL", "CHAOS_START_DELAY_SECONDS", "CHAOS_ERROR_RATE",
    "RESET_TOKEN", "RELEASE_SECURITY_SUMMARY", "RELEASE_SECURITY_SUMMARY_FILE",
]


@pytest.fixture
def load_app(monkeypatch, tmp_path):
    """load_app(**env) -> freshly imported app module, wired to an empty fakeredis."""
    def _load(**env):
        for name in APP_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
        # Point the RBAC card at an empty dir by default, so a real token on the test machine is ignored.
        monkeypatch.setenv("SA_DIR", str(tmp_path / "no-sa"))
        for name, value in env.items():
            monkeypatch.setenv(name, str(value))
        sys.modules.pop("app", None)
        mod = importlib.import_module("app")
        mod.r = fakeredis.FakeRedis(decode_responses=True)
        return mod
    yield _load
    sys.modules.pop("app", None)


@pytest.fixture
def api(load_app):
    mod = load_app()
    return mod, mod.app.test_client()


def _registry() -> Registry:
    resources = []
    for path in CONTRACTS.glob("*.schema.json"):
        doc = json.loads(path.read_text())
        resources.append((doc["$id"], Resource.from_contents(doc)))
    return Registry().with_resources(resources)


REGISTRY = _registry()


def assert_contract(name: str, payload) -> None:
    schema = json.loads((CONTRACTS / f"{name}.schema.json").read_text())
    errors = sorted(Draft202012Validator(schema, registry=REGISTRY).iter_errors(payload), key=str)
    assert not errors, f"{name} contract violated: " + "; ".join(e.message for e in errors)


class _JSONHandler(BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self):
        if self.path not in self.routes:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(self.routes[self.path]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def json_server():
    """json_server({path: payload}) -> base URL of a tiny local HTTP server (e.g. fake ECS metadata)."""
    servers = []

    def _start(routes: dict) -> str:
        handler = type("Handler", (_JSONHandler,), {"routes": routes})
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    yield _start
    for srv in servers:
        srv.shutdown()
