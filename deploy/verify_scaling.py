"""Prove Golit's horizontal-scale claim locally: a server-side invalidation raised on one
node reaches a client whose SSE stream lives on a *different* node, fanned out through Redis.

Two single-worker `golit run` processes share one Redis (`GOLIT_REDIS_URL`), the same wiring
as two hosts behind the sticky load balancer in `docker-compose.yml` — here the two processes
stand in for the two hosts, since the fan-out path (publish → Redis → every worker's SSE) is
identical. Node A runs the publisher (`GOLIT_PUBLISH=1`); node B does not. We connect an SSE
client to **node B** and assert it receives `node:clock` events — which can only have
originated on node A and crossed Redis.

    docker run -d --rm -p 6379:6379 redis:7-alpine          # a Redis to share
    GOLIT_REDIS_URL=redis://localhost:6379 python deploy/verify_scaling.py

Exits non-zero on failure. Needs the dev deps (httpx) and a built golit in the venv.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

REDIS_URL = os.environ.get("GOLIT_REDIS_URL", "redis://localhost:6379")
APP = "deploy/scaling_demo/app.py"
NODE_A = 8101  # the publisher
NODE_B = 8102  # SSE client connects here — no publisher of its own
GOLIT = str(Path(sys.executable).with_name("golit"))


def _spawn(port: int, publish: bool, redis: bool) -> subprocess.Popen[bytes]:
    env = dict(os.environ)
    if redis:
        env["GOLIT_REDIS_URL"] = REDIS_URL
    else:
        env.pop("GOLIT_REDIS_URL", None)  # in-memory pubsub: isolated per process
    if publish:
        env["GOLIT_PUBLISH"] = "1"
    else:
        env.pop("GOLIT_PUBLISH", None)
    return subprocess.Popen(
        [GOLIT, "run", APP, "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_ready(port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"http://localhost:{port}/", timeout=1.0).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"node on :{port} never became ready")


def _await_cross_node_event(timeout: float = 10.0) -> bool:
    """Open an SSE stream on node B and wait for a `node:clock` event from node A."""
    with httpx.Client(base_url=f"http://localhost:{NODE_B}") as client:
        client.get("/")  # establishes the golit_session cookie + a session on node B
        deadline = time.time() + timeout
        with client.stream("GET", "/events", timeout=httpx.Timeout(timeout, read=3.0)) as r:
            try:
                for line in r.iter_lines():
                    if "node:clock" in line:
                        return True
                    if time.time() > deadline:
                        return False
            except httpx.ReadTimeout:
                return False
    return False


def _case(redis: bool, timeout: float) -> bool:
    """Bring up node A (publisher) + node B, return whether B's SSE client saw node:clock."""
    procs = [_spawn(NODE_A, publish=True, redis=redis), _spawn(NODE_B, publish=False, redis=redis)]
    try:
        _wait_ready(NODE_A)
        _wait_ready(NODE_B)
        return _await_cross_node_event(timeout=timeout)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


def main() -> int:
    print(f"redis = {REDIS_URL}")
    # With Redis: the invalidation on node A must reach node B's client.
    with_redis = _case(redis=True, timeout=10.0)
    print(f"  with Redis    -> node B saw node:clock: {with_redis}")
    # Control — no Redis: each process has its own in-memory pubsub, so node A's invalidation
    # must NOT reach node B. This rules out any non-Redis path and proves Redis is load-bearing.
    without_redis = _case(redis=False, timeout=4.0)
    print(f"  without Redis -> node B saw node:clock: {without_redis}")
    if with_redis and not without_redis:
        print("PASS: cross-node fan-out works, and only because of Redis")
        return 0
    print("FAIL: expected with-Redis=True, without-Redis=False")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
