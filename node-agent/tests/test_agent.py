"""node-agent unit tests: /proc parsing, k8s-less defaults, ECS naming. Run: pytest node-agent/tests"""
import importlib
import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


@pytest.fixture
def load_agent(monkeypatch, tmp_path):
    def _load(**env):
        for k in ("NODE_NAME", "ECS_CONTAINER_METADATA_URI_V4", "HOST_PROC", "HOST_POD_LOGS", "APP_VERSION"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("ALIVE_FILE", str(tmp_path / "alive"))
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        sys.modules.pop("agent", None)
        return importlib.import_module("agent")
    return _load


def fake_proc(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "meminfo").write_text("MemTotal:  1000 kB\nMemFree: 100 kB\nMemAvailable:  250 kB\n")
    (proc / "loadavg").write_text("0.42 0.30 0.20 1/100 1234\n")
    (proc / "uptime").write_text("7200.5 100.0\n")
    return proc


def test_collect_reads_host_proc(load_agent, tmp_path):
    logs = tmp_path / "pods"
    (logs / "ns_pod-a_uid").mkdir(parents=True)
    (logs / "ns_pod-b_uid").mkdir()
    agent = load_agent(HOST_PROC=str(fake_proc(tmp_path)), HOST_POD_LOGS=str(logs), NODE_NAME="node-1",
                       APP_VERSION="2.0")
    p = agent.collect()
    assert p["node"] == "node-1" and p["mem_used_pct"] == 75 and p["load1"] == 0.42
    assert p["uptime_hours"] == 2.0 and p["pods_on_node"] == 2 and p["agent_version"] == "2.0"
    assert p["az"] is None and p["launch_type"] is None


def test_collect_without_kubernetes_mounts(load_agent, tmp_path):
    agent = load_agent(HOST_PROC=str(tmp_path / "missing"), HOST_POD_LOGS=str(tmp_path / "missing"))
    p = agent.collect()
    assert p["node"] == "unknown-node" and p["pods_on_node"] is None and p["mem_used_pct"] is None
    assert p["load1"] is None and p["uptime_hours"] == 0


def test_ecs_task_is_the_node(load_agent):
    task = {"TaskARN": "arn:aws:ecs:eu-central-1:111122223333:task/podpoll/0f1e2d3c4b5a69788796a5b4c3d2e1f0",
            "AvailabilityZone": "eu-central-1a", "LaunchType": "FARGATE"}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(task).encode())

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        agent = load_agent(ECS_CONTAINER_METADATA_URI_V4=f"http://127.0.0.1:{srv.server_address[1]}/v4/x")
        p = agent.collect()
        assert p["node"] == "task-0f1e2d3c4b5a" and p["az"] == "eu-central-1a" and p["launch_type"] == "FARGATE"
    finally:
        srv.shutdown()


def test_unreachable_ecs_metadata_is_harmless(load_agent):
    agent = load_agent(ECS_CONTAINER_METADATA_URI_V4="http://127.0.0.1:9/v4/x")
    assert agent.ECS_TASK == {} and agent.NODE_NAME == "unknown-node"


def test_touch_alive_writes_the_health_file(load_agent, tmp_path):
    agent = load_agent()
    agent.touch_alive()
    assert (tmp_path / "alive").exists()
