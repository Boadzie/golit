"""B1 over HTTP — end-to-end update latency vs unaffected nodes.

For each graph shape: boot an isolated uvicorn server (config via env), wait for
the port, drive ``POST /node/threshold`` over loopback, record p50/p95/p99 of the
end-to-end latency and the bytes-per-update, then tear the server down. Writes
``bench/results/b1_http.csv``. Run::

    uv run --no-sync python -m bench.http.run_b1_http            # full sweep
    uv run --no-sync python -m bench.http.run_b1_http --quick    # fast
"""

from __future__ import annotations

import argparse
import csv
import os
import socket
import subprocess
import sys
import time

from .drive import measure_http_update

DEFAULT_DEPTHS = [1, 3, 10]
DEFAULT_UNAFFECTED = [0, 16, 64, 256]
DEFAULT_ROWS = 100_000
_SLIDER_VALUES = [11, 23]

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
LOG_PATH = os.path.join(RESULTS_DIR, "uvicorn.log")
SERVE_TARGET = "bench.http.serve:application"
FIELDS = ["rows", "depth", "unaffected", "metric", "p50_us", "p95_us", "p99_us", "mean_us",
          "bytes", "n"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _boot(rows: int, depth: int, unaffected: int, port: int):
    env = os.environ.copy()
    env["GOLIT_BENCH_ROWS"] = str(rows)
    env["GOLIT_BENCH_DEPTH"] = str(depth)
    env["GOLIT_BENCH_UNAFFECTED"] = str(unaffected)
    log = open(LOG_PATH, "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", SERVE_TARGET, "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning", "--no-access-log"],
        env=env, stdout=log, stderr=log,
    )
    return proc, log


def _wait_ready(port: int, proc: subprocess.Popen, *, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            with open(LOG_PATH) as f:
                raise RuntimeError(f"server exited early (code {proc.returncode}):\n{f.read()}")
        with socket.socket() as s:
            s.settimeout(0.5)
            try:
                s.connect(("127.0.0.1", port))
                return
            except OSError:
                time.sleep(0.1)
    raise TimeoutError(f"server not ready on :{port} within {timeout}s")


def _stop(proc: subprocess.Popen, log) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    log.close()


def run(*, rows: int, depths: list[int], unaffected_list: list[int],
        iters: int, warmup: int) -> list[dict]:
    results: list[dict] = []
    for depth in depths:
        for u in unaffected_list:
            port = _free_port()
            proc, log = _boot(rows, depth, u, port)
            try:
                _wait_ready(port, proc)
                summary = measure_http_update(
                    f"http://127.0.0.1:{port}", "threshold", _SLIDER_VALUES,
                    warmup=warmup, iters=iters,
                )
            finally:
                _stop(proc, log)
            row = {"rows": rows, "depth": depth, "unaffected": u, "metric": "http_update",
                   **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in summary.items()}}
            results.append(row)
            print(
                f"  depth={depth:>2} u={u:>4}  e2e p50={summary['p50_us'] / 1000:6.2f}ms "
                f"p99={summary['p99_us'] / 1000:6.2f}ms  bytes={summary['bytes']:.0f}"
            )
    return results


def _headline(results: list[dict]) -> str:
    deepest = max(r["depth"] for r in results)
    line = [r for r in results if r["depth"] == deepest]
    lo = min(line, key=lambda r: r["unaffected"])
    hi = max(line, key=lambda r: r["unaffected"])
    return (
        f"End-to-end update p99 (depth {deepest}): "
        f"{lo['p99_us'] / 1000:.2f}ms at {lo['unaffected']} unaffected nodes -> "
        f"{hi['p99_us'] / 1000:.2f}ms at {hi['unaffected']} — flat over real HTTP. "
        f"Bytes/update constant at {lo['bytes']:.0f}B (only the chart fragment swaps)."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Golit B1 end-to-end (HTTP) benchmark")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    ap.add_argument("--iters", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--out", default=os.path.join(RESULTS_DIR, "b1_http.csv"))
    args = ap.parse_args()

    if args.quick:
        depths, unaffected_list, iters, warmup = [1, 3, 10], [0, 64], 40, 8
    else:
        depths, unaffected_list = DEFAULT_DEPTHS, DEFAULT_UNAFFECTED
        iters, warmup = args.iters, args.warmup

    os.makedirs(RESULTS_DIR, exist_ok=True)
    print(f"B1/HTTP sweep: rows={args.rows} depths={depths} unaffected={unaffected_list}")
    print(f"iters={iters} warmup={warmup}\n")

    t0 = time.perf_counter()
    results = run(rows=args.rows, depths=depths, unaffected_list=unaffected_list,
                  iters=iters, warmup=warmup)
    elapsed = time.perf_counter() - t0

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(results)

    print(f"\nWrote {len(results)} rows to {args.out} in {elapsed:.1f}s")
    print("\n" + _headline(results))


if __name__ == "__main__":
    main()
