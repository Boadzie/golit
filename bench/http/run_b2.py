"""B2 — concurrency scaling: does Golit hold latency under simultaneous sessions?

The production axis B1 doesn't touch. Two sweeps at a fixed graph shape
(``GOLIT_BENCH_*`` defaults: 100K rows, depth 3), driven by the closed-loop load
generator in :mod:`bench.http.load`:

1. **concurrency** — one server instance, sweep the number of simultaneous sessions
   ``C`` ∈ {1..64}. Shows the per-instance capacity: throughput rises with ``C``
   until the instance saturates, and where p99 starts to bend.
2. **scaling** — fix a saturating ``C`` and add **sticky instances** ``N`` ∈ {1,2,4}
   (each session pinned to one instance, the cookie-hash-LB model). Golit keeps
   session state worker-local, so this is how it scales horizontally: throughput
   should rise ~linearly with ``N`` and p99 recover.

Writes ``bench/results/b2.csv``. Run::

    uv run --no-sync python -m bench.http.run_b2            # full
    uv run --no-sync python -m bench.http.run_b2 --quick    # fast
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import time
from typing import IO

from .load import measure_concurrent
from .serverctl import boot, free_port, stop, wait_ready

DEFAULT_ROWS = 100_000
DEFAULT_DEPTH = 3
DEFAULT_UNAFFECTED = 0
_SLIDER_VALUES = [11, 23, 37, 53, 71]

DEFAULT_CONCURRENCY = [1, 2, 4, 8, 16, 32, 64]
DEFAULT_INSTANCES = [1, 2, 4]
DEFAULT_SCALE_CONCURRENCY = 32

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
FIELDS = ["phase", "instances", "concurrency", "p50_us", "p95_us", "p99_us", "mean_us",
          "throughput_rps", "n"]


def _log_path(k: int) -> str:
    return os.path.join(RESULTS_DIR, f"uvicorn_b2_{k}.log")


def _instances(n: int, rows: int, depth: int, unaffected: int) -> tuple[list, list[str]]:
    procs: list[tuple[subprocess.Popen, IO]] = []
    urls: list[str] = []
    for k in range(n):
        port = free_port()
        log_path = _log_path(k)
        proc, log = boot(rows, depth, unaffected, port, log_path)
        wait_ready(port, proc, log_path)
        procs.append((proc, log))
        urls.append(f"http://127.0.0.1:{port}")
    return procs, urls


def _teardown(procs: list) -> None:
    for proc, log in procs:
        stop(proc, log)


def _row(phase: str, instances: int, concurrency: int, summary: dict) -> dict:
    return {"phase": phase, "instances": instances, "concurrency": concurrency,
            **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in summary.items()}}


def run(*, rows: int, depth: int, unaffected: int, concurrency_levels: list[int],
        instance_levels: list[int], scale_concurrency: int,
        warmup_s: float, measure_s: float) -> list[dict]:
    results: list[dict] = []

    # Sweep 1: one instance, rising concurrency.
    print("concurrency sweep (1 instance):")
    procs, urls = _instances(1, rows, depth, unaffected)
    try:
        for c in concurrency_levels:
            s = measure_concurrent(urls, "threshold", _SLIDER_VALUES,
                                   concurrency=c, warmup_s=warmup_s, measure_s=measure_s)
            results.append(_row("concurrency", 1, c, s))
            print(f"  C={c:>3}  p50={s['p50_us']/1000:6.2f}ms p99={s['p99_us']/1000:6.2f}ms "
                  f"thru={s['throughput_rps']:8.0f} req/s")
    finally:
        _teardown(procs)

    # Sweep 2: fixed saturating load, sticky instances 1..N.
    print(f"\nscaling sweep (C={scale_concurrency}, sticky instances):")
    for n in instance_levels:
        procs, urls = _instances(n, rows, depth, unaffected)
        try:
            s = measure_concurrent(urls, "threshold", _SLIDER_VALUES,
                                   concurrency=scale_concurrency,
                                   warmup_s=warmup_s, measure_s=measure_s)
            results.append(_row("scaling", n, scale_concurrency, s))
            print(f"  N={n:>2}  p50={s['p50_us']/1000:6.2f}ms p99={s['p99_us']/1000:6.2f}ms "
                  f"thru={s['throughput_rps']:8.0f} req/s")
        finally:
            _teardown(procs)

    return results


def _headline(results: list[dict]) -> str:
    conc = [r for r in results if r["phase"] == "concurrency"]
    lo = min(conc, key=lambda r: r["concurrency"])
    hi = max(conc, key=lambda r: r["concurrency"])
    scaling = [r for r in results if r["phase"] == "scaling"]
    line = ""
    if scaling:
        s1 = min(scaling, key=lambda r: r["instances"])
        sN = max(scaling, key=lambda r: r["instances"])
        factor = sN["throughput_rps"] / max(s1["throughput_rps"], 1e-9)
        line = (f" Sticky scaling {s1['instances']}->{sN['instances']} instances: "
                f"throughput {s1['throughput_rps']:.0f}->{sN['throughput_rps']:.0f} req/s "
                f"({factor:.1f}x).")
    return (
        f"Single instance: p99 {lo['p99_us']/1000:.2f}ms @ C={lo['concurrency']} -> "
        f"{hi['p99_us']/1000:.2f}ms @ C={hi['concurrency']}; "
        f"peak throughput {max(r['throughput_rps'] for r in conc):.0f} req/s.{line}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Golit B2 concurrency-scaling benchmark")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    ap.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    ap.add_argument("--unaffected", type=int, default=DEFAULT_UNAFFECTED)
    ap.add_argument("--measure-s", type=float, default=3.0)
    ap.add_argument("--warmup-s", type=float, default=1.0)
    ap.add_argument("--out", default=os.path.join(RESULTS_DIR, "b2.csv"))
    args = ap.parse_args()

    if args.quick:
        concurrency_levels, instance_levels = [1, 8, 32], [1, 2]
        scale_conc, measure_s, warmup_s = 16, 1.5, 0.5
    else:
        concurrency_levels, instance_levels = DEFAULT_CONCURRENCY, DEFAULT_INSTANCES
        scale_conc, measure_s, warmup_s = DEFAULT_SCALE_CONCURRENCY, args.measure_s, args.warmup_s

    os.makedirs(RESULTS_DIR, exist_ok=True)
    print(f"B2 concurrency: rows={args.rows} depth={args.depth} unaffected={args.unaffected}")
    print(f"concurrency={concurrency_levels} instances={instance_levels} "
          f"scale_C={scale_conc} measure={measure_s}s warmup={warmup_s}s\n")

    t0 = time.perf_counter()
    results = run(rows=args.rows, depth=args.depth, unaffected=args.unaffected,
                  concurrency_levels=concurrency_levels, instance_levels=instance_levels,
                  scale_concurrency=scale_conc, warmup_s=warmup_s, measure_s=measure_s)
    elapsed = time.perf_counter() - t0

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(results)

    print(f"\nWrote {len(results)} rows to {args.out} in {elapsed:.1f}s")
    print("\n" + _headline(results))


if __name__ == "__main__":
    main()
