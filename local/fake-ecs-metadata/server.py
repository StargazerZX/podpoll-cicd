"""A fake ECS task metadata endpoint (v4), so "ECS mode" can be demoed without AWS.

Real ECS injects ECS_CONTAINER_METADATA_URI_V4 into every container; GET <uri>/task returns the
task's metadata. Here every CALLER gets its own stable fake task, derived from its IP address, so
two API replicas look like two Fargate tasks in different AZs. Stdlib only.
"""
import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ENV = os.getenv("PODPOLL_ENV", "default")
REVISION = os.getenv("FAKE_TASK_REVISION", "7")
REGION = os.getenv("FAKE_REGION", "eu-central-1")
ACCOUNT = "111122223333"   # the AWS documentation example account ID; obviously fake


def fake_task(client_ip: str) -> dict:
    task_id = hashlib.sha256(client_ip.encode()).hexdigest()[:32]
    az = REGION + "abc"[int(task_id, 16) % 3]
    cluster = f"podpoll-{ENV}"
    return {
        "Cluster": f"arn:aws:ecs:{REGION}:{ACCOUNT}:cluster/{cluster}",
        "TaskARN": f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/{cluster}/{task_id}",
        "Family": f"podpoll-{ENV}-api",
        "Revision": REVISION,
        "DesiredStatus": "RUNNING",
        "KnownStatus": "RUNNING",
        "AvailabilityZone": az,
        "LaunchType": "FARGATE",
        "Limits": {"CPU": 0.25, "Memory": 512},
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        ip = self.client_address[0]
        if self.path == "/healthz":
            body = {"ok": True}
        elif self.path.startswith("/v4/") and self.path.endswith("/task"):
            body = fake_task(ip)
        elif self.path.startswith("/v4/"):
            body = {"DockerId": hashlib.sha256(ip.encode()).hexdigest()[:12], "Name": "fake",
                    "Labels": {"com.amazonaws.ecs.task-arn": fake_task(ip)["TaskARN"]}}
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print("fake ECS metadata endpoint on :8080", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # noqa: S104
