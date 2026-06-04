"""B-memo over **real HTTP** — the memoization win with transport on both sides.

``run_memo.py`` isolates the engine (in-process ``Session.update`` vs a recompute call).
This one keeps the wire: each engine serves the shared-upstream app from its own
production server on loopback, and a sequential client drives a ``threshold_a`` move
end-to-end.

* **Golit** — uvicorn serving :mod:`bench.http.serve_memo`; a ``POST /node/threshold_a``
  re-renders only ``view_a`` (``heavy`` is clean → memoized).
* **Dash** — waitress serving :class:`bench.apps.dash_memo.DashMemoTwin`; the client POSTs
  the real ``/_dash-update-component`` for ``chart_a``, whose callback recomputes ``heavy``.

Both run the same ``memo_heavy``/``memo_payload`` and both ship a raw-dict bar spec, so the
only difference measured is recompute-vs-memoize — now including Flask vs Litestar dispatch
and the socket round trip. We sweep the shared-upstream size. Writes
``results/b_memo_http.csv``::

    uv run --no-sync python -m bench.run_memo_http
    uv run --no-sync python -m bench.run_memo_http --quick
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time

from .http.drive import measure_dash_http, measure_http_update
from .http.serverctl import boot, free_port, stop, wait_ready

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
_GOLIT_TARGET = "bench.http.serve_memo:application"
_SLIDER_VALUES = [11, 23, 37, 53, 71]
FIELDS = ["framework", "transport", "rows", "p50_us", "p95_us", "p99_us", "mean_us",
          "bytes", "n", "speedup"]


def _log(name: str) -> str:
    return os.path.join(RESULTS_DIR, f"{name}.log")


def _measure_golit(*, rows: int, warmup: int, iters: int) -> dict:
    port = free_port()
    log_path = _log("golit_memo_http")
    proc, log = boot(rows, 0, 0, port, log_path, target=_GOLIT_TARGET)
    try:
        wait_ready(port, proc, log_path)
        return measure_http_update(f"http://127.0.0.1:{port}", "threshold_a",
                                   _SLIDER_VALUES, warmup=warmup, iters=iters)
    finally:
        stop(proc, log)


def _boot_dash_memo(rows: int, port: int, log_path: str):
    env = os.environ.copy()
    env["GOLIT_BENCH_ROWS"] = str(rows)
    env["GOLIT_BENCH_PORT"] = str(port)
    log = open(log_path, "w")
    proc = subprocess.Popen([sys.executable, "-m", "bench.apps.dash_memo_server"],
                            env=env, stdout=log, stderr=log)
    return proc, log


def _measure_dash(*, rows: int, warmup: int, iters: int) -> dict:
    port = free_port()
    log_path = _log("dash_memo_http")
    proc, log = _boot_dash_memo(rows, port, log_path)
    try:
        wait_ready(port, proc, log_path)
        return measure_dash_http(f"http://127.0.0.1:{port}", _SLIDER_VALUES,
                                 warmup=warmup, iters=iters,
                                 output_id="chart_a", input_id="threshold_a")
    finally:
        stop(proc, log)


def run(*, rows_levels: list[int], warmup: int, iters: int) -> list[dict]:
    results: list[dict] = []
    for rows in rows_levels:
        g = _measure_golit(rows=rows, warmup=warmup, iters=iters)
        d = _measure_dash(rows=rows, warmup=warmup, iters=iters)
        speedup = d["p50_us"] / max(g["p50_us"], 1e-9)
        for name, transport, s, sp in (
            ("Golit (memo)", "uvicorn + dirty subgraph", g, speedup),
            ("Dash (recompute)", "waitress + callback", d, 1.0),
        ):
            results.append({"framework": name, "transport": transport, "rows": rows,
                            **{k: (round(v, 3) if isinstance(v, float) else v)
                               for k, v in s.items()},
                            "speedup": round(sp, 2)})
        print(f"  {rows:>9,}r  Golit {g['p50_us'] / 1000:6.2f}ms ({g['bytes']:.0f} B)  "
              f"Dash {d['p50_us'] / 1000:6.2f}ms ({d['bytes']:.0f} B)  -> {speedup:.1f}x")
    return results


def _headline(results: list[dict]) -> str:
    lines = []
    for rows in sorted({r["rows"] for r in results}):
        by = {r["framework"]: r for r in results if r["rows"] == rows}
        g, d = by["Golit (memo)"], by["Dash (recompute)"]
        lines.append(f"{rows:>9,} rows: Golit {g['p50_us'] / 1000:5.2f}ms vs Dash "
                     f"{d['p50_us'] / 1000:5.2f}ms ({g['speedup']:.1f}x).")
    return ("Shared-upstream update over real HTTP (move one slider; the other view's "
            "upstream stays clean):\n  " + "\n  ".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description="Golit vs Dash memoization over real HTTP")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--rows", default="100000,500000,1000000,2000000",
                    help="comma-separated shared-upstream sizes to sweep")
    ap.add_argument("--iters", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--out", default=os.path.join(RESULTS_DIR, "b_memo_http.csv"))
    args = ap.parse_args()

    iters, warmup = (40, 8) if args.quick else (args.iters, args.warmup)
    rows_levels = [int(x) for x in args.rows.split(",")]

    os.makedirs(RESULTS_DIR, exist_ok=True)
    print(f"B-memo over HTTP — Golit vs Dash: rows={rows_levels} iters={iters} warmup={warmup}\n")

    t0 = time.perf_counter()
    results = run(rows_levels=rows_levels, warmup=warmup, iters=iters)
    elapsed = time.perf_counter() - t0

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(results)

    print(f"\nWrote {len(results)} rows to {args.out} in {elapsed:.1f}s")
    print("\n" + _headline(results))


if __name__ == "__main__":
    main()
