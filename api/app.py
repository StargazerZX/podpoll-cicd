"""
PodPoll API  --  the "backend" tier.

A tiny Flask app that:
  * stores votes in Redis OR PostgreSQL
  * tells you WHICH instance / node / environment answered  (so load balancing & envs become visible)
  * tells you WHICH BUILD is running: version, git SHA, CI run   (so pipelines become visible)
  * receives heartbeats from the node-agent  (one per node, host, or ECS task)
  * on Kubernetes, asks the API server "what pods exist?" using its OWN ServiceAccount identity
    -- and shows you exactly what Kubernetes says back, allowed or not.

It runs unchanged on Kubernetes, Amazon ECS (Fargate) and plain Docker. Everything
environment-specific comes from environment variables: Kubernetes fills some in via the
Downward API, ECS via the task metadata endpoint, Docker via the Compose env files.
"""
import base64
import hmac
import json
import logging
import os
import random
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import redis
from flask import Flask, jsonify, request

app = Flask(__name__)
log = logging.getLogger("podpoll")


# --- small env helpers --------------------------------------------------------
def env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def env_float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        return min(hi, max(lo, float(os.getenv(name, default))))
    except ValueError:
        return default


# --- build provenance (stamped into the image by CI as --build-arg -> ENV) ------
# Anything here can come from a branch name or a CI variable, so it is sanitised before it is
# shown anywhere. The frontend's stamp.sh applies the SAME rules at image build time.
def clean(value, allowed: str, default: str, max_len: int = 64) -> str:
    """Replace every character outside `allowed` (a regex character class body) with '-'."""
    value = (value or "").strip()
    if not value:
        return default
    return re.sub(f"[^{allowed}]", "-", value)[:max_len]


def clean_url(value) -> str:
    value = (value or "").strip()
    if re.fullmatch(r"https?://[0-9A-Za-z._~:/?#@!$&()*+,;=%-]+", value) and len(value) <= 512:
        return value
    return ""


def clean_sha(value) -> str:
    value = (value or "").strip().lower()
    return value if re.fullmatch(r"[0-9a-f]{7,40}", value) else "unknown"


def clean_time(value) -> str:
    value = (value or "").strip()
    return value if re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value) else "unknown"


def build_info(env=os.environ) -> dict:
    sha = clean_sha(env.get("GIT_SHA"))
    source = clean_url(env.get("SOURCE_URL"))
    return {
        "version": clean(env.get("APP_VERSION"), "0-9A-Za-z.+-", "dev"),
        "git_sha": sha,
        "git_sha_short": sha[:7] if sha != "unknown" else "unknown",
        "git_ref": clean(env.get("GIT_REF"), "0-9A-Za-z._/+-", "unknown", 128),
        "build_id": clean(env.get("BUILD_ID"), "0-9A-Za-z._-", "local"),
        "build_url": clean_url(env.get("BUILD_URL")),
        "ci_system": clean(env.get("CI_SYSTEM"), "0-9a-z-", "local", 32),
        "build_time": clean_time(env.get("BUILD_TIME")),
        "source_url": source,
        "commit_url": f"{source}/commit/{sha}" if source and sha != "unknown" else "",
    }


BUILD = build_info()


# --- where am I running? kubernetes | ecs | docker ------------------------------
PLATFORMS = ("kubernetes", "ecs", "docker")


def detect_platform(env=os.environ) -> str:
    explicit = (env.get("PLATFORM") or "").strip().lower()
    if explicit in PLATFORMS:
        return explicit
    if env.get("KUBERNETES_SERVICE_HOST"):   # kubelet injects this into every pod
        return "kubernetes"
    if env.get("ECS_CONTAINER_METADATA_URI_V4"):   # the ECS agent injects this into every container
        return "ecs"
    return "docker"


def load_ecs_metadata(base_uri, timeout: float = 1.0) -> dict:
    """Read ECS task metadata v4 ONCE at startup. Short timeout, and never crash: an empty
    dict just means the UI shows less detail."""
    if not base_uri:
        return {}
    try:
        with urllib.request.urlopen(f"{base_uri}/task", timeout=timeout) as resp:
            task = json.loads(resp.read())
    except Exception as e:  # noqa: BLE001 -- metadata is decoration, never a reason to die
        log.warning("could not read ECS task metadata: %s", e)
        return {}
    return {
        "task_id": str(task.get("TaskARN", "")).rsplit("/", 1)[-1] or "unknown",
        "cluster": str(task.get("Cluster", "")).rsplit("/", 1)[-1] or "unknown",
        "family": task.get("Family", "unknown"),
        "revision": str(task.get("Revision", "unknown")),
        "az": task.get("AvailabilityZone", "unknown"),
        "launch_type": task.get("LaunchType", "unknown"),
    }


PLATFORM = detect_platform()
ECS_TASK = (load_ecs_metadata(os.getenv("ECS_CONTAINER_METADATA_URI_V4"))
            if PLATFORM == "ecs" else {})

# --- configuration (12-factor style: all from env vars) ---------------------
REDIS_HOST = os.getenv("REDIS_HOST", "redis")          # <-- a Service name (k8s, Compose, ECS Service Connect)
# NOTE: not called REDIS_PORT on purpose! Kubernetes auto-injects env vars for every Service in the
# namespace (for a Service named "redis": REDIS_PORT=tcp://10.96.x.x:6379). Those would clash.
REDIS_TCP_PORT = int(os.getenv("REDIS_TCP_PORT", "6379"))
# Identity: k8s Downward API > ECS task ID > container hostname.
POD_NAME = os.getenv("POD_NAME") or ECS_TASK.get("task_id") or socket.gethostname()
POD_NAMESPACE = os.getenv("POD_NAMESPACE", "unknown")   # Downward API
# "Node": k8s Downward API > ECS "AZ / launch type" (each Fargate task is its own micro-VM).
NODE_NAME = (os.getenv("NODE_NAME")
             or (f"{ECS_TASK['az']} / {ECS_TASK['launch_type']}" if ECS_TASK else "unknown"))
APP_VERSION = BUILD["version"]                          # baked into the image at build time
NODE_TTL_SECONDS = int(os.getenv("NODE_TTL_SECONDS", "30"))
# The environment shown in the badge: dev | staging | prod | preview. On k8s the namespace is a
# fine default; on ECS and Docker there is no namespace, so set PODPOLL_ENV.
PODPOLL_ENV = os.getenv("PODPOLL_ENV") or POD_NAMESPACE

# --- chaos switches: all OFF by default. /healthz ignores every one of them. -----------------
CHAOS_READY_FAIL = env_bool("CHAOS_READY_FAIL")                         # /readyz -> 503
CHAOS_START_DELAY_SECONDS = env_float("CHAOS_START_DELAY_SECONDS", 0, 0, 600)
CHAOS_ERROR_RATE = env_float("CHAOS_ERROR_RATE", 0, 0, 1)               # share of votes -> 500

# Optional protection for POST /api/reset. Unset (the default) = open, an accepted risk for a demo.
RESET_TOKEN = os.getenv("RESET_TOKEN", "")

# --- the vote store. Unset DB_HOST => Redis (ephemeral). Set => PostgreSQL. ----------------
# Same trick as REDIS_TCP_PORT: never call this DB_PORT, or a Service named "db" would clash.
DB_HOST = os.getenv("DB_HOST")            # e.g. "postgres-0.postgres" -- set by the podpoll-db Secret
DB_TCP_PORT = int(os.getenv("DB_TCP_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "podpoll")
DB_USER = os.getenv("DB_USER", "podpoll")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
USE_POSTGRES = bool(DB_HOST)

if USE_POSTGRES:
    import psycopg  # only imported when actually needed


# --- the poll itself: configurable, so every workshop can ask its own question ---------------
DEFAULT_QUESTION = "Which pipeline gate saves you most often?"
DEFAULT_OPTIONS = ["Secret scan", "Unit tests", "SAST", "Dependency scan", "Image scan", "Code review"]


def parse_options(raw) -> list:
    """POLL_OPTIONS is comma-separated. Fewer than 2 usable options => fall back to the defaults."""
    seen = []
    for item in (raw or "").split(","):
        item = item.strip()[:40]
        if item and item not in seen:
            seen.append(item)
    return seen[:12] if len(seen) >= 2 else list(DEFAULT_OPTIONS)


POLL_QUESTION = (os.getenv("POLL_QUESTION") or DEFAULT_QUESTION).strip()[:200]
OPTIONS = parse_options(os.getenv("POLL_OPTIONS"))

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
    except Exception:  # noqa: BLE001 -- any failure means "not ready"
        return False


def unavailable(err: Exception):
    return jsonify(error="database unavailable", detail=str(err)), 503


def startup_delay() -> None:
    """CHAOS_START_DELAY_SECONDS: a slow-starting release. Called by gunicorn's on_starting hook
    (gunicorn.conf.py) BEFORE it binds the port, so health checks genuinely fail meanwhile."""
    if CHAOS_START_DELAY_SECONDS > 0:
        log.warning("chaos: delaying startup by %ss", CHAOS_START_DELAY_SECONDS)
        time.sleep(CHAOS_START_DELAY_SECONDS)


# --- PostgreSQL vote store ---------------------------------------
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


# --- health endpoints (k8s probes, ECS/ALB health checks, Docker HEALTHCHECK) ----
@app.get("/healthz")
def healthz():
    """Liveness: is the PROCESS alive? Deliberately does NOT check the database,
    and ignores every chaos switch (otherwise a bad release would restart-loop, not roll back)."""
    return "ok\n", 200


@app.get("/readyz")
def readyz():
    """Readiness: can this instance do useful work? Needs the active vote store.
    When this fails, Kubernetes removes the pod from the Service's endpoints, the ALB marks the
    ECS task unhealthy, and a deployment circuit breaker / Argo CD health check notices."""
    if CHAOS_READY_FAIL:
        return "chaos: CHAOS_READY_FAIL=true\n", 503
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
        # --- additive fields (CI/CD edition) ---
        env=PODPOLL_ENV,
        platform=PLATFORM,
        git_sha=BUILD["git_sha"],
        ci_system=BUILD["ci_system"],
        task=ECS_TASK or None,
        reset_protected=bool(RESET_TOKEN),
        chaos={
            "ready_fail": CHAOS_READY_FAIL,
            "start_delay_seconds": CHAOS_START_DELAY_SECONDS,
            "error_rate": CHAOS_ERROR_RATE,
        },
    )


# --- "which build is this?" -------------------------------------------------
@app.get("/api/build")
def build():
    return jsonify(BUILD)


# --- "what did the pipeline find in this release?" ----------------------------
# The pipeline passes its security summary to the running app: as an env var on ECS
# (RELEASE_SECURITY_SUMMARY, compact JSON) or as a ConfigMap file on Kubernetes
# (RELEASE_SECURITY_SUMMARY_FILE). No data => {"available": false} and the UI hides the card.
def release_security() -> dict:
    raw = os.getenv("RELEASE_SECURITY_SUMMARY", "")
    path = os.getenv("RELEASE_SECURITY_SUMMARY_FILE", "")
    if not raw and path:
        try:
            with open(path) as f:
                raw = f.read()
        except OSError:
            raw = ""
    if not raw.strip():
        return {"available": False}
    try:
        summary = json.loads(raw)
    except ValueError:
        return {"available": False, "error": "release security summary is not valid JSON"}
    if not isinstance(summary, dict):
        return {"available": False, "error": "release security summary must be a JSON object"}
    return {"available": True, "summary": summary}


@app.get("/api/release/security")
def release_security_endpoint():
    return jsonify(release_security())


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
        question=POLL_QUESTION,
    )


@app.post("/api/vote")
def vote():
    body = request.get_json(silent=True) or {}
    option = body.get("option")
    if option not in OPTIONS:
        return jsonify(error=f"option must be one of {OPTIONS}"), 400
    if CHAOS_ERROR_RATE and random.random() < CHAOS_ERROR_RATE:  # noqa: S311 -- not crypto
        return jsonify(error="chaos: injected failure (CHAOS_ERROR_RATE)"), 500
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
    if RESET_TOKEN:
        supplied = request.headers.get("X-Reset-Token", "")
        # compare_digest: constant-time, so the token can't be guessed byte by byte from timings
        if not hmac.compare_digest(supplied.encode(), RESET_TOKEN.encode()):
            return jsonify(error="reset requires a valid X-Reset-Token header"), 403
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


# --- node heartbeats (sent by the node-agent: DaemonSet on k8s, sidecar on ECS) ----
# Always Redis, even in Postgres mode: heartbeats are ephemeral cache data, not votes.
# (Talking point: not every kind of data belongs in the same store.)
@app.post("/api/nodes/heartbeat")
def heartbeat():
    body = request.get_json(silent=True) or {}
    node = body.get("node")
    if not node:
        return jsonify(error="'node' is required"), 400
    body["last_seen"] = time.time()
    try:
        # SET ... EX: the key vanishes after NODE_TTL_SECONDS. If an agent dies, its node disappears.
        r.set(f"node:{node}", json.dumps(body), ex=NODE_TTL_SECONDS)
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


# --- Kubernetes only: RBAC. The API asks Kubernetes "what pods exist?" using its OWN identity ------
SA_DIR = os.getenv("SA_DIR", "/var/run/secrets/kubernetes.io/serviceaccount")


def _decode_jwt_sub(token: str) -> str:
    """Pull the 'sub' claim out of the SA token, e.g. system:serviceaccount:default:default.
    DISPLAY ONLY: this does not verify the token's signature. The apiserver does that part."""
    try:
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload.get("sub", "unknown")
    except Exception:  # noqa: BLE001 -- display only; never fail the request
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
        except Exception:  # noqa: BLE001 -- non-JSON error body: fall back to the HTTP reason
            message = str(e)
        return jsonify(allowed=False, identity=identity, namespace=namespace,
                        status=e.code, message=message, pods=[])
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as e:
        return jsonify(allowed=False, identity=identity, namespace=namespace,
                        status=None, message=f"could not reach the API server: {e}", pods=[])


if __name__ == "__main__":  # local dev only; in the container we use gunicorn
    startup_delay()
    app.run(host="0.0.0.0", port=5000)  # noqa: S104
