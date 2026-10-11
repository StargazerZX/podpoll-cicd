"""
PodPoll API  --  the "backend" tier.

A tiny Flask app that:
  * stores votes in Redis OR PostgreSQL          (Modules 2/6: Deployments+storage, Module 7: StatefulSets)
  * tells you WHICH pod / node / namespace answered   (so Services & namespaces become visible)
  * receives heartbeats from the node-agent DaemonSet  (so DaemonSets become visible)
  * asks the Kubernetes API "what pods exist?" using its OWN ServiceAccount identity
    (Module 8: RBAC) -- and shows you exactly what Kubernetes says back, allowed or not.

Everything environment-specific comes from environment variables, which the
Kubernetes manifests fill in (some of them via the Downward API).
"""
import base64
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import redis
from flask import Flask, jsonify, request

app = Flask(__name__)

# --- configuration (12-factor style: all from env vars) ---------------------
REDIS_HOST = os.getenv("REDIS_HOST", "redis")          # <-- a Kubernetes Service name!
# NOTE: not called REDIS_PORT on purpose! Kubernetes auto-injects env vars for every Service in the
# namespace (for a Service named "redis": REDIS_PORT=tcp://10.96.x.x:6379). Those would clash.
REDIS_TCP_PORT = int(os.getenv("REDIS_TCP_PORT", "6379"))
POD_NAME = os.getenv("POD_NAME", socket.gethostname())  # Downward API
POD_NAMESPACE = os.getenv("POD_NAMESPACE", "unknown")   # Downward API
NODE_NAME = os.getenv("NODE_NAME", "unknown")           # Downward API
APP_VERSION = os.getenv("APP_VERSION", "dev")           # baked into the image at build time
NODE_TTL_SECONDS = int(os.getenv("NODE_TTL_SECONDS", "30"))

# --- Module 6/7: the vote store. Unset DB_HOST => Redis (ephemeral). Set => PostgreSQL. -----
# Same trick as REDIS_TCP_PORT: never call this DB_PORT, or a Service named "db" would clash.
DB_HOST = os.getenv("DB_HOST")            # e.g. "postgres-0.postgres" -- set by the podpoll-db Secret
DB_TCP_PORT = int(os.getenv("DB_TCP_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "podpoll")
DB_USER = os.getenv("DB_USER", "podpoll")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
USE_POSTGRES = bool(DB_HOST)

if USE_POSTGRES:
    import psycopg  # only imported when actually needed

OPTIONS = ["Pod", "Deployment", "Service", "Namespace", "DaemonSet", "ConfigMap"]

# Short timeouts on purpose: if the store is gone we want to fail fast, not hang.
r = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_TCP_PORT,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
)

# Has this worker process already made sure the "votes" table exists in Postgres?
# One flag per process (gunicorn worker) -- cheap, and wrong at worst once per restart.
_schema_ready = False


def redis_ok() -> bool:
    try:
        return bool(r.ping())
    except Exception:
        return False


def unavailable(err: Exception):
    return jsonify(error="database unavailable", detail=str(err)), 503


# --- Module 6/7: PostgreSQL vote store ---------------------------------------
def pg_connect():
    """A short-lived connection per request. Fine at workshop scale; a real app would pool."""
    return psycopg.connect(
        host=DB_HOST, port=DB_TCP_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
        connect_timeout=2, application_name=POD_NAME,
    )


def pg_ensure_schema(conn) -> None:
    """Create the votes table exactly once per process.

    Two API pods can both start at the same moment and both run `CREATE TABLE IF NOT EXISTS`
    at the same moment -- that's a genuine Postgres race (a duplicate-key error on the
    catalog, `pg_type_typname_nsp_index`), not a hypothetical one. An advisory lock
    (an app-chosen integer, scoped to this one transaction) makes the two pods take turns.
    """
    global _schema_ready
    if _schema_ready:
        return
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(4242)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS votes (
                id bigserial PRIMARY KEY,
                option text NOT NULL,
                api_pod text,
                created_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    _schema_ready = True


def pg_ok() -> bool:
    try:
        with pg_connect() as conn:
            pg_ensure_schema(conn)
        return True
    except psycopg.Error:
        return False


def db_server_name() -> str:
    """Ask Postgres who it thinks it is. The StatefulSet sets cluster_name=$(POD_NAME),
    so this proves whether postgres-0 or postgres-1 answered."""
    try:
        with pg_connect() as conn, conn.cursor() as cur:
            cur.execute("SHOW cluster_name")
            row = cur.fetchone()
            return row[0] if row and row[0] else "postgres"
    except psycopg.Error:
        return "unknown"


def store_ok() -> bool:
    return pg_ok() if USE_POSTGRES else redis_ok()


# --- health endpoints (used by the probes in the Deployment) ----------------
@app.get("/healthz")
def healthz():
    """Liveness: is the PROCESS alive? Deliberately does NOT check the database."""
    return "ok\n", 200


@app.get("/readyz")
def readyz():
    """Readiness: can this pod do useful work? Needs the active vote store.
    When this fails, Kubernetes removes the pod from the Service's endpoints."""
    if store_ok():
        return "ready\n", 200
    return "store unreachable\n", 503


# --- "who answered?" --------------------------------------------------------
@app.get("/api/info")
def info():
    return jsonify(
        pod=POD_NAME,
        namespace=POD_NAMESPACE,
        node=NODE_NAME,
        version=APP_VERSION,
        store="postgres" if USE_POSTGRES else "redis",
        db_host=DB_HOST if USE_POSTGRES else REDIS_HOST,
        db_server=db_server_name() if USE_POSTGRES else POD_NAME,
        db_ok=store_ok(),
    )


# --- the poll ---------------------------------------------------------------
@app.get("/api/results")
def results():
    if USE_POSTGRES:
        try:
            with pg_connect() as conn:
                pg_ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute("SELECT option, count(*) FROM votes GROUP BY option")
                    counts = dict(cur.fetchall())
        except psycopg.Error as e:
            return unavailable(e)
    else:
        try:
            counts = r.hgetall("votes")
        except redis.RedisError as e:
            return unavailable(e)
    rows = [{"option": o, "votes": int(counts.get(o, 0))} for o in OPTIONS]
    return jsonify(
        results=rows,
        total=sum(x["votes"] for x in rows),
        served_by=POD_NAME,
        store="postgres" if USE_POSTGRES else "redis",
    )


@app.post("/api/vote")
def vote():
    body = request.get_json(silent=True) or {}
    option = body.get("option")
    if option not in OPTIONS:
        return jsonify(error=f"option must be one of {OPTIONS}"), 400
    if USE_POSTGRES:
        try:
            with pg_connect() as conn:
                pg_ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO votes (option, api_pod) VALUES (%s, %s)", (option, POD_NAME)
                    )
        except psycopg.Error as e:
            return unavailable(e)
    else:
        try:
            r.hincrby("votes", option, 1)
        except redis.RedisError as e:
            return unavailable(e)
    return jsonify(ok=True, option=option, served_by=POD_NAME)


@app.post("/api/reset")
def reset():
    if USE_POSTGRES:
        try:
            with pg_connect() as conn:
                pg_ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute("TRUNCATE votes")
        except psycopg.Error as e:
            return unavailable(e)
    else:
        try:
            r.delete("votes")
        except redis.RedisError as e:
            return unavailable(e)
    return jsonify(ok=True)


# --- node heartbeats (sent by the node-agent DaemonSet) ---------------------
# Always Redis, even in Postgres mode: heartbeats are ephemeral cache data, not votes.
# (Module 7 talking point: not every kind of data belongs in the same store.)
@app.post("/api/nodes/heartbeat")
def heartbeat():
    body = request.get_json(silent=True) or {}
    node = body.get("node")
    if not node:
        return jsonify(error="'node' is required"), 400
    body["last_seen"] = time.time()
    try:
        # SETEX: the key vanishes after NODE_TTL_SECONDS. If an agent dies, its node disappears.
        r.setex(f"node:{node}", NODE_TTL_SECONDS, json.dumps(body))
    except redis.RedisError as e:
        return unavailable(e)
    return jsonify(ok=True)


@app.get("/api/nodes")
def nodes():
    try:
        keys = sorted(r.scan_iter("node:*"))
        raw = [r.get(k) for k in keys]
    except redis.RedisError as e:
        return unavailable(e)
    now = time.time()
    out = []
    for item in raw:
        if not item:  # expired between SCAN and GET
            continue
        n = json.loads(item)
        n["age_seconds"] = round(now - n.get("last_seen", now))
        out.append(n)
    return jsonify(nodes=out)


# --- Module 8: RBAC. The API asks Kubernetes "what pods exist?" using its OWN identity ------
SA_DIR = os.getenv("SA_DIR", "/var/run/secrets/kubernetes.io/serviceaccount")


def _decode_jwt_sub(token: str) -> str:
    """Pull the 'sub' claim out of the SA token, e.g. system:serviceaccount:default:default.
    DISPLAY ONLY: this does not verify the token's signature. The apiserver does that part."""
    try:
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload.get("sub", "unknown")
    except Exception:
        return "unknown"


def _apiserver_base_url() -> str:
    """Build the API server URL the same way client-go does: from the env vars kubelet
    injects into every pod. Falls back to the well-known in-cluster DNS name."""
    host = os.getenv("KUBERNETES_SERVICE_HOST")
    port = os.getenv("KUBERNETES_SERVICE_PORT", "443")
    if host:
        if ":" in host:  # IPv6 literal needs brackets in a URL
            host = f"[{host}]"
        return f"https://{host}:{port}"
    return "https://kubernetes.default.svc"


@app.get("/api/cluster/pods")
def cluster_pods():
    token_path = os.path.join(SA_DIR, "token")
    ca_path = os.path.join(SA_DIR, "ca.crt")
    ns_path = os.path.join(SA_DIR, "namespace")

    # Read fresh on every request: kubelet ROTATES the projected token in the background,
    # so caching it would eventually mean using an expired one.
    if not os.path.exists(token_path):
        return jsonify(
            allowed=False, identity="unknown", namespace=POD_NAMESPACE,
            status=None, message="No ServiceAccount token mounted "
                                  "(automountServiceAccountToken: false?)",
            pods=[],
        )

    with open(token_path) as f:
        token = f.read().strip()
    namespace = POD_NAMESPACE
    if os.path.exists(ns_path):
        with open(ns_path) as f:
            namespace = f.read().strip()
    identity = _decode_jwt_sub(token)

    qs = urllib.parse.urlencode({"labelSelector": "part-of=podpoll"})
    url = f"{_apiserver_base_url()}/api/v1/namespaces/{namespace}/pods?{qs}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})

    try:
        ctx = ssl.create_default_context(cafile=ca_path if os.path.exists(ca_path) else None)
        with urllib.request.urlopen(req, timeout=3, context=ctx) as resp:
            body = json.loads(resp.read())
        pods = []
        for item in body.get("items", []):
            conditions = item.get("status", {}).get("conditions", [])
            ready = next((c["status"] for c in conditions if c.get("type") == "Ready"), "Unknown")
            pods.append({
                "name": item["metadata"]["name"],
                "phase": item.get("status", {}).get("phase", "Unknown"),
                "node": item.get("spec", {}).get("nodeName", "unknown"),
                "ready": ready,
            })
        return jsonify(allowed=True, identity=identity, namespace=namespace,
                        status=200, message="OK", pods=pods)
    except urllib.error.HTTPError as e:
        # The apiserver's Status object is genuinely useful -- pass its message straight through.
        try:
            status_body = json.loads(e.read())
            message = status_body.get("message", str(e))
        except Exception:
            message = str(e)
        return jsonify(allowed=False, identity=identity, namespace=namespace,
                        status=e.code, message=message, pods=[])
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as e:
        return jsonify(allowed=False, identity=identity, namespace=namespace,
                        status=None, message=f"could not reach the API server: {e}", pods=[])


if __name__ == "__main__":  # local dev only; in the container we use gunicorn
    app.run(host="0.0.0.0", port=5000)
