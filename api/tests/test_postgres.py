"""Postgres-mode integration tests (marker: pg). They need a real server:

    docker run -d --name podpoll-pg-test -p 55432:5432 -e POSTGRES_USER=podpoll \
        -e POSTGRES_PASSWORD=test-only -e POSTGRES_DB=podpoll postgres:17-alpine -c cluster_name=pg-test
    PG_TEST_HOST=127.0.0.1 PG_TEST_PORT=55432 PG_TEST_PASSWORD=test-only pytest -m pg

Without PG_TEST_HOST they are skipped (`scripts/test-api.sh` starts the container for you).
"""
import multiprocessing
import os

import pytest
from conftest import assert_contract

pytestmark = pytest.mark.pg

PG = {
    "DB_HOST": os.getenv("PG_TEST_HOST", ""),
    "DB_TCP_PORT": os.getenv("PG_TEST_PORT", "5432"),
    "DB_NAME": os.getenv("PG_TEST_DB", "podpoll"),
    "DB_USER": os.getenv("PG_TEST_USER", "podpoll"),
    "DB_PASSWORD": os.getenv("PG_TEST_PASSWORD", ""),
}

if not PG["DB_HOST"]:
    pytest.skip("PG_TEST_HOST not set", allow_module_level=True)


@pytest.fixture
def pg_app(load_app):
    mod = load_app(**PG, POD_NAME="api-pg-1")
    with mod.pg_connect() as conn, conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS votes")
    mod._schema_ready = False
    return mod


def test_info_reports_postgres(pg_app):
    d = pg_app.app.test_client().get("/api/info").get_json()
    assert_contract("info", d)
    assert d["store"] == "postgres" and d["db_host"] == PG["DB_HOST"] and d["db_ok"] is True
    assert d["db_server"] == os.getenv("PG_TEST_CLUSTER_NAME", "pg-test")


def test_vote_results_reset(pg_app):
    client = pg_app.app.test_client()
    assert client.get("/readyz").status_code == 200
    for opt in ("SAST", "SAST", "Unit tests"):
        assert client.post("/api/vote", json={"option": opt}).status_code == 200
    d = client.get("/api/results").get_json()
    assert_contract("results", d)
    counts = {x["option"]: x["votes"] for x in d["results"]}
    assert counts["SAST"] == 2 and counts["Unit tests"] == 1 and d["store"] == "postgres"
    with pg_app.pg_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT api_pod FROM votes")
        assert cur.fetchall() == [("api-pg-1",)]
    assert client.post("/api/reset").get_json() == {"ok": True}
    assert client.get("/api/results").get_json()["total"] == 0


def test_heartbeats_still_use_redis_in_postgres_mode(pg_app):
    client = pg_app.app.test_client()
    client.post("/api/nodes/heartbeat", json={"node": "n1"})
    assert pg_app.r.exists("node:n1")


def _race_worker(barrier, results):
    import app as mod  # inherited via fork: same config, its own per-process _schema_ready flag
    mod._schema_ready = False
    try:
        with mod.pg_connect() as conn:
            barrier.wait(timeout=10)
            mod.pg_ensure_schema(conn)
        results.put("ok")
    except Exception as e:  # noqa: BLE001
        results.put(repr(e))


def test_concurrent_schema_creation_does_not_race(pg_app):
    """Eight 'replicas' create the table at the same instant. Without pg_advisory_xact_lock this
    intermittently fails with a duplicate key on pg_type_typname_nsp_index."""
    ctx = multiprocessing.get_context("fork")
    barrier, results = ctx.Barrier(8), ctx.Queue()
    procs = [ctx.Process(target=_race_worker, args=(barrier, results)) for _ in range(8)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
    outcomes = [results.get(timeout=5) for _ in procs]
    assert outcomes == ["ok"] * 8


def test_postgres_down_gives_503(load_app):
    mod = load_app(**{**PG, "DB_HOST": "127.0.0.1", "DB_TCP_PORT": "9"})
    client = mod.app.test_client()
    assert client.get("/readyz").status_code == 503
    assert client.get("/healthz").status_code == 200
    for method, path, body in [("get", "/api/results", None), ("post", "/api/vote", {"option": "SAST"}),
                               ("post", "/api/reset", None)]:
        res = getattr(client, method)(path, json=body)
        assert res.status_code == 503 and res.get_json()["error"] == "database unavailable"
    d = client.get("/api/info").get_json()
    assert d["db_ok"] is False and d["db_server"] == "unknown"
