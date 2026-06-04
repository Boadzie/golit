"""Golit vs Dash over **real HTTP** — the fair, full-stack update-latency test.

The in-process render comparison (``run_b1_dash.py``) excludes transport on both sides.
This one keeps it: each framework serves the *same real chart* from its own production
server on loopback, and a single sequential client drives a slider move end-to-end —
server framing + routing + dispatch + render + serialize + the socket round trip. It is
the HTTP analog of ``run_b1_http.py``, extended to Dash, and architecture-matched so the
comparison isolates the framework rather than the rendering choice:

* **Golit (Plotly)** — uvicorn serving a Golit app whose view returns a Plotly figure;
  Golit ships it as a spec mount, exactly like Dash. Matched to Dash, this is the
  framework-vs-framework number (Litestar/ASGI + dirty subgraph vs Flask/WSGI +
  callback_context).
* **Dash** — waitress (a production WSGI server, for parity with uvicorn) serving the
  Dash twin; the client POSTs the real ``/_dash-update-component`` callback request.
* **Golit (SVG)** — the same Golit server but rendering the chart to an SVG fragment
  server-side (no client runtime) — the extra path Dash doesn't have, here over the wire.

All on loopback, one sequential client (B1 latency, not B2 concurrency). Writes
``results/b1_dash_http.csv``::

    uv run --no-sync python -m bench.run_b1_dash_http
    uv run --no-sync python -m bench.run_b1_dash_http --quick
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
_SLIDER_VALUES = [11, 23, 37, 53, 71]
FIELDS = ["framework", "transport", "rows", "depth", "p50_us", "p95_us", "p99_us",
          "mean_us", "bytes", "n"]


def _log(name: str) -> str:
    return os.path.join(RESULTS_DIR, f"{name}.log")


def _boot_dash(rows: int, depth: int, unaffected: int, port: int, log_path: str):
    """Start the Dash twin under waitress on ``port``; mirror of serverctl.boot."""
    env = os.environ.copy()
    env["GOLIT_BENCH_ROWS"] = str(rows)
    env["GOLIT_BENCH_DEPTH"] = str(depth)
    env["GOLIT_BENCH_UNAFFECTED"] = str(unaffected)
    env["GOLIT_BENCH_PORT"] = str(port)
    log = open(log_path, "w")
    proc = subprocess.Popen([sys.executable, "-m", "bench.apps.dash_server"],
                            env=env, stdout=log, stderr=log)
    return proc, log


def _measure_golit(chart: str, *, rows: int, depth: int, unaffected: int,
                   warmup: int, iters: int) -> dict:
    port = free_port()
    log_path = _log(f"golit_http_{chart}")
    proc, log = boot(rows, depth, unaffected, port, log_path, chart=chart)
    try:
        wait_ready(port, proc, log_path)
        return measure_http_update(f"http://127.0.0.1:{port}", "threshold",
                                   _SLIDER_VALUES, warmup=warmup, iters=iters)
    finally:
        stop(proc, log)


def _measure_dash(*, rows: int, depth: int, unaffected: int,
                  warmup: int, iters: int) -> dict:
    port = free_port()
    log_path = _log("dash_http")
    proc, log = _boot_dash(rows, depth, unaffected, port, log_path)
    try:
        wait_ready(port, proc, log_path)
        return measure_dash_http(f"http://127.0.0.1:{port}", _SLIDER_VALUES,
                                 warmup=warmup, iters=iters)
    finally:
        stop(proc, log)


def run(*, rows: int, depth: int, unaffected: int, warmup: int, iters: int) -> list[dict]:
    cases = [
        ("Golit (Plotly)", "uvicorn + figure JSON", lambda: _measure_golit(
            "plotly", rows=rows, depth=depth, unaffected=unaffected, warmup=warmup, iters=iters)),
        ("Golit (spec)", "uvicorn + raw dict spec", lambda: _measure_golit(
            "spec", rows=rows, depth=depth, unaffected=unaffected, warmup=warmup, iters=iters)),
        ("Dash", "waitress + figure JSON", lambda: _measure_dash(
            rows=rows, depth=depth, unaffected=unaffected, warmup=warmup, iters=iters)),
        ("Golit (SVG)", "uvicorn + server SVG", lambda: _measure_golit(
            "svg", rows=rows, depth=depth, unaffected=unaffected, warmup=warmup, iters=iters)),
    ]
    results: list[dict] = []
    for name, transport, measure in cases:
        s = measure()
        results.append({"framework": name, "transport": transport, "rows": rows, "depth": depth,
                        **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()}})
        print(f"  {name:<15} {transport:<22} e2e p50={s['p50_us'] / 1000:6.2f}ms "
              f"p99={s['p99_us'] / 1000:6.2f}ms  bytes={s['bytes']:.0f}")
    return results


def _headline(results: list[dict]) -> str:
    by = {r["framework"]: r for r in results}
    gpl, d = by["Golit (Plotly)"], by["Dash"]
    gspec, gsvg = by["Golit (spec)"], by["Golit (SVG)"]
    speedup = d["p50_us"] / max(gspec["p50_us"], 1e-9)
    return (
        f"Over real HTTP, same 16-bar chart. Returning a Plotly *figure*, Golit "
        f"{gpl['p50_us'] / 1000:.2f}ms ({gpl['bytes']:.0f} B) ties idiomatic Dash "
        f"{d['p50_us'] / 1000:.2f}ms ({d['bytes']:.0f} B) — same figure build + to_json on "
        f"both. Returning a raw dict via chart_spec, Golit (spec) drops to "
        f"{gspec['p50_us'] / 1000:.2f}ms ({gspec['bytes']:.0f} B): {speedup:.1f}x faster than "
        f"figure-returning Dash, skipping the graph_objects build and to_json. "
        f"Golit(SVG) {gsvg['p50_us'] / 1000:.2f}ms: server-rendered, no client runtime."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Golit vs Dash over real HTTP (B1 latency)")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--rows", type=int, default=100_000)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--unaffected", type=int, default=0)
    ap.add_argument("--iters", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--out", default=os.path.join(RESULTS_DIR, "b1_dash_http.csv"))
    args = ap.parse_args()

    iters, warmup = (40, 8) if args.quick else (args.iters, args.warmup)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    print(f"B1 over HTTP — Golit vs Dash: rows={args.rows} depth={args.depth} "
          f"iters={iters} warmup={warmup}\n")

    t0 = time.perf_counter()
    results = run(rows=args.rows, depth=args.depth, unaffected=args.unaffected,
                  warmup=warmup, iters=iters)
    elapsed = time.perf_counter() - t0

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(results)

    print(f"\nWrote {len(results)} rows to {args.out} in {elapsed:.1f}s")
    print("\n" + _headline(results))


if __name__ == "__main__":
    main()
