"""
node-agent  --  the DaemonSet workload.

One copy of this runs on EVERY node. Every INTERVAL seconds it looks at the node it is
running on (through hostPath mounts) and reports to the PodPoll API, which shows it in the UI.

Standard library only, so the image stays tiny.
"""
import json
import os
import platform
import signal
import socket
import sys
import time
import urllib.error
import urllib.request

API_URL = os.getenv("API_URL", "http://api:5000")            # <-- a Kubernetes Service name again
INTERVAL = int(os.getenv("INTERVAL_SECONDS", "10"))
NODE_NAME = os.getenv("NODE_NAME", "unknown-node")           # Downward API: spec.nodeName
POD_NAME = os.getenv("POD_NAME", socket.gethostname())       # Downward API: metadata.name
HOST_PROC = os.getenv("HOST_PROC", "/host/proc")             # hostPath: /proc
HOST_POD_LOGS = os.getenv("HOST_POD_LOGS", "/host/var/log/pods")  # hostPath: /var/log/pods


def read_meminfo() -> dict:
    info = {}
    try:
        with open(f"{HOST_PROC}/meminfo") as f:
            for line in f:
                key, value = line.split(":", 1)
                info[key] = int(value.strip().split()[0])  # kB
    except OSError:
        pass
    return info


def read_first_float(path: str, index: int = 0):
    try:
        with open(path) as f:
            return float(f.read().split()[index])
    except (OSError, ValueError, IndexError):
        return None


def count_pods_on_node():
    """Every pod on a node has a log directory under /var/log/pods. Counting them tells us
    how many pods this node hosts -- across ALL namespaces. (hostPath ignores namespaces!)"""
    try:
        return len(os.listdir(HOST_POD_LOGS))
    except OSError:
        return None


def collect() -> dict:
    mem = read_meminfo()
    total = mem.get("MemTotal")
    avail = mem.get("MemAvailable")
    mem_used_pct = round(100 * (total - avail) / total) if total and avail else None
    return {
        "node": NODE_NAME,
        "agent_pod": POD_NAME,
        "kernel": platform.release(),
        "cpus": os.cpu_count(),
        "load1": read_first_float(f"{HOST_PROC}/loadavg", 0),
        "uptime_hours": round((read_first_float(f"{HOST_PROC}/uptime", 0) or 0) / 3600, 1),
        "mem_used_pct": mem_used_pct,
        "pods_on_node": count_pods_on_node(),
    }


def send(payload: dict) -> None:
    req = urllib.request.Request(
        f"{API_URL}/api/nodes/heartbeat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        resp.read()


def main() -> None:
    # Python running as PID 1 in a container ignores SIGTERM by default, which would make
    # `kubectl delete pod` hang for the full 30 s grace period. Exit promptly instead.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print(f"node-agent starting on node={NODE_NAME} pod={POD_NAME} -> {API_URL}", flush=True)
    while True:
        payload = collect()
        try:
            send(payload)
            print(f"heartbeat ok   node={payload['node']} pods_on_node={payload['pods_on_node']} "
                  f"load1={payload['load1']} mem_used={payload['mem_used_pct']}%", flush=True)
        except (urllib.error.URLError, OSError) as e:
            # Never crash because the API is briefly unavailable -- just try again.
            print(f"heartbeat FAILED ({e}); will retry in {INTERVAL}s", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
