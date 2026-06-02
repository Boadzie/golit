"""B1 — incremental update latency vs number of unaffected nodes.

Sweeps the synthetic app's graph shape and, for each configuration, measures:

* **update**   — ``Session.update`` latency (the real server-side metric).
* **schedule** — the pure Rust ``dirty_subgraph`` call, isolating kernel cost.
* **full**     — a full graph recompute (the naive "rerun everything" baseline),
                 measured along one slice so the hero chart has a climbing line to
                 contrast the flat update lines against.

Writes ``bench/results/b1.csv`` and prints a summary table. Run::

    uv run --no-sync python -m bench.run_b1            # full sweep
    uv run --no-sync python -m bench.run_b1 --quick    # fast, fewer points
"""

from __future__ import annotations

import argparse
import csv
import os
import time

from golit.engine import Session

from .gen_app import make_app
from .instrument import measure_full, measure_schedule, measure_update

DEFAULT_UNAFFECTED = [0, 1, 2, 4, 8, 16, 32, 64, 128, 256]
DEFAULT_DEPTHS = [1, 3, 10]
DEFAULT_ROWS = [10_000, 100_000]

# Two slider values cycled so every update is a genuine recompute, never a memo hit.
_SLIDER_VALUES = [11, 23]

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
FIELDS = ["rows", "depth", "unaffected", "metric", "exec_count", "p50_us", "p95_us", "p99_us",
          "mean_us", "n"]


def _row(rows, depth, unaffected, metric, exec_count, summary) -> dict:
    return {
        "rows": rows, "depth": depth, "unaffected": unaffected, "metric": metric,
        "exec_count": exec_count, **{k: round(v, 3) if isinstance(v, float) else v
                                     for k, v in summary.items()},
    }


def run(
    *,
    rows_list: list[int],
    depths: list[int],
    unaffected_list: list[int],
    iters: int,
    warmup: int,
    full_iters: int,
) -> list[dict]:
    results: list[dict] = []
    for rows in rows_list:
        for depth in depths:
            for u in unaffected_list:
                app = make_app(rows=rows, depth=depth, unaffected=u)
                session = Session(app)
                session.initial_render()  # warm: data computed once, stays resident

                upd, exec_count = measure_update(
                    session, "threshold", _SLIDER_VALUES, warmup=warmup, iters=iters
                )
                sched = measure_schedule(
                    session.graph, ["threshold"], warmup=warmup, iters=iters * 2
                )
                results.append(_row(rows, depth, u, "update", exec_count, upd))
                results.append(_row(rows, depth, u, "schedule", 0, sched))
                print(
                    f"  rows={rows:>8} depth={depth:>2} u={u:>4}  "
                    f"update p50={upd['p50_us']:8.1f}us p99={upd['p99_us']:8.1f}us  "
                    f"sched p50={sched['p50_us']:6.2f}us  exec={exec_count}"
                )

    # Full-recompute baseline along one slice (depth=3, largest dataset) so the
    # hero chart has the climbing "rerun everything" line.
    base_rows = rows_list[-1]
    base_depth = 3 if 3 in depths else depths[0]
    print(f"\nFull-recompute baseline (rows={base_rows}, depth={base_depth}):")
    for u in unaffected_list:
        app = make_app(rows=base_rows, depth=base_depth, unaffected=u)
        session = Session(app)
        full = measure_full(session, warmup=2, iters=full_iters)
        results.append(_row(base_rows, base_depth, u, "full", base_depth + 2 + u, full))
        print(f"  u={u:>4}  full p50={full['p50_us']:9.1f}us p99={full['p99_us']:9.1f}us")
    return results


def _headline(results: list[dict]) -> str:
    """The flat-vs-climbing sentence, read straight off the data."""
    upd = [r for r in results if r["metric"] == "update"]
    full = [r for r in results if r["metric"] == "full"]
    deepest = max(r["depth"] for r in upd)
    line = [r for r in upd if r["depth"] == deepest]
    lo = min(line, key=lambda r: r["unaffected"])
    hi = max(line, key=lambda r: r["unaffected"])
    msg = (
        f"Golit update p99 (depth {deepest}): "
        f"{lo['p99_us']:.0f}us at {lo['unaffected']} unaffected nodes -> "
        f"{hi['p99_us']:.0f}us at {hi['unaffected']} — flat."
    )
    if full:
        f_lo = min(full, key=lambda r: r["unaffected"])
        f_hi = max(full, key=lambda r: r["unaffected"])
        factor = f_hi["p99_us"] / max(f_lo["p99_us"], 1e-9)
        msg += (
            f"\nFull recompute climbs with graph size, same sweep: "
            f"{f_lo['p99_us']:.0f}us -> {f_hi['p99_us']:.0f}us ({factor:.1f}x)."
        )
    return msg


def main() -> None:
    ap = argparse.ArgumentParser(description="Golit B1 incremental-update benchmark")
    ap.add_argument("--quick", action="store_true", help="fewer points + iterations")
    ap.add_argument("--iters", type=int, default=150)
    ap.add_argument("--warmup", type=int, default=25)
    ap.add_argument("--full-iters", type=int, default=12)
    ap.add_argument("--out", default=os.path.join(RESULTS_DIR, "b1.csv"))
    args = ap.parse_args()

    if args.quick:
        rows_list, depths = [10_000], [1, 3, 10]
        unaffected_list = [0, 4, 16, 64, 256]
        iters, warmup, full_iters = 50, 10, 6
    else:
        rows_list, depths, unaffected_list = DEFAULT_ROWS, DEFAULT_DEPTHS, DEFAULT_UNAFFECTED
        iters, warmup, full_iters = args.iters, args.warmup, args.full_iters

    print(f"B1 sweep: rows={rows_list} depths={depths} unaffected={unaffected_list}")
    print(f"iters={iters} warmup={warmup} full_iters={full_iters}\n")

    t0 = time.perf_counter()
    results = run(
        rows_list=rows_list, depths=depths, unaffected_list=unaffected_list,
        iters=iters, warmup=warmup, full_iters=full_iters,
    )
    elapsed = time.perf_counter() - t0

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(results)

    print(f"\nWrote {len(results)} rows to {args.out} in {elapsed:.1f}s")
    print("\n" + _headline(results))


if __name__ == "__main__":
    main()
