"""Boot / readiness / teardown for the benchmark uvicorn server(s).

Shared by the B1 (single server) and B2 (N sticky instances) harnesses. Each
instance is one ``uvicorn`` process serving ``serve:application`` with the graph
shape supplied through ``GOLIT_BENCH_*`` env vars, on its own port and log file.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from typing import IO

SERVE_TARGET = "bench.http.serve:application"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def boot(rows: int, depth: int, unaffected: int, port: int, log_path: str,
         *, workers: int = 1, chart: str = "text",
         target: str = SERVE_TARGET) -> tuple[subprocess.Popen, IO]:
    """Start one uvicorn instance; return the process and its open log file.

    ``target`` selects the ASGI app — the single-chain ``serve`` by default, or
    ``bench.http.serve_memo:application`` for the shared-upstream memoization bench."""
    env = os.environ.copy()
    env["GOLIT_BENCH_ROWS"] = str(rows)
    env["GOLIT_BENCH_DEPTH"] = str(depth)
    env["GOLIT_BENCH_UNAFFECTED"] = str(unaffected)
    env["GOLIT_BENCH_CHART"] = chart
    log = open(log_path, "w")
    cmd = [sys.executable, "-m", "uvicorn", target, "--host", "127.0.0.1",
           "--port", str(port), "--log-level", "warning", "--no-access-log"]
    if workers > 1:
        cmd += ["--workers", str(workers)]
    proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=log)
    return proc, log


def wait_ready(port: int, proc: subprocess.Popen, log_path: str, *, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            with open(log_path) as f:
                raise RuntimeError(f"server exited early (code {proc.returncode}):\n{f.read()}")
        with socket.socket() as s:
            s.settimeout(0.5)
            try:
                s.connect(("127.0.0.1", port))
                return
            except OSError:
                time.sleep(0.1)
    raise TimeoutError(f"server not ready on :{port} within {timeout}s")


def stop(proc: subprocess.Popen, log: IO) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    log.close()
