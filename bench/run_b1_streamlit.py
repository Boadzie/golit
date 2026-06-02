"""B1 for Streamlit — server-side script-rerun latency via AppTest.

Sweeps the same {depth, unaffected} grid as the in-process Golit B1 and measures
Streamlit's per-interaction rerun time (input change → updated app) with
``@st.cache_data`` enabled. ``AppTest`` runs the script in-process and excludes
the browser websocket, so this is **server compute** — directly comparable to
Golit's in-process ``Session.update`` (also server compute, no transport).

``AppTest.run()`` adds a fixed per-call harness overhead, and our app renders a
constant two elements (slider + markdown) regardless of ``unaffected`` — so the
overhead is constant in the swept variable. Absolute ms are therefore an upper
bound, but the **slope** (climb vs flat as unaffected grows) is exactly the claim.

    uv run --no-sync python -m bench.run_b1_streamlit            # full sweep
    uv run --no-sync python -m bench.run_b1_streamlit --quick    # fast
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import time

from streamlit.testing.v1 import AppTest

from .instrument import percentiles

# AppTest runs the script off the main Streamlit runtime, which logs a benign
# "missing ScriptRunContext" warning per rerun — silence it so the table is clean.
logging.getLogger("streamlit").setLevel(logging.ERROR)

APP = os.path.join(os.path.dirname(__file__), "apps", "streamlit_app.py")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

DEFAULT_DEPTHS = [1, 3, 10]
DEFAULT_UNAFFECTED = [0, 4, 16, 64, 128, 256]
DEFAULT_ROWS = 100_000
# A handful of distinct slider positions; the affected chain is uncached, so it
# recomputes every rerun regardless — these just keep the interaction realistic.
_SLIDER_VALUES = [11, 23, 37, 53, 71]
FIELDS = ["rows", "depth", "unaffected", "metric", "p50_us", "p95_us", "p99_us", "mean_us", "n"]


def measure(rows: int, depth: int, unaffected: int, *, warmup: int, iters: int) -> dict[str, float]:
    os.environ["GOLIT_BENCH_ROWS"] = str(rows)
    os.environ["GOLIT_BENCH_DEPTH"] = str(depth)
    os.environ["GOLIT_BENCH_UNAFFECTED"] = str(unaffected)

    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    if at.exception:
        raise RuntimeError(f"streamlit app errored: {at.exception}")

    n = len(_SLIDER_VALUES)
    idx = 0
    for _ in range(warmup):
        at.slider[0].set_value(_SLIDER_VALUES[idx % n]).run()
        idx += 1

    samples: list[int] = []
    for _ in range(iters):
        v = _SLIDER_VALUES[idx % n]
        idx += 1
        t0 = time.perf_counter_ns()
        at.slider[0].set_value(v).run()
        samples.append(time.perf_counter_ns() - t0)
    return percentiles(samples)


def run(*, rows: int, depths: list[int], unaffected_list: list[int],
        iters: int, warmup: int) -> list[dict]:
    results: list[dict] = []
    for depth in depths:
        for u in unaffected_list:
            summary = measure(rows, depth, u, warmup=warmup, iters=iters)
            results.append({
                "rows": rows, "depth": depth, "unaffected": u, "metric": "streamlit_rerun",
                **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in summary.items()},
            })
            print(
                f"  depth={depth:>2} u={u:>4}  rerun p50={summary['p50_us'] / 1000:7.2f}ms "
                f"p99={summary['p99_us'] / 1000:7.2f}ms"
            )
    return results


def _headline(results: list[dict]) -> str:
    deepest = max(r["depth"] for r in results)
    line = [r for r in results if r["depth"] == deepest]
    lo = min(line, key=lambda r: r["unaffected"])
    hi = max(line, key=lambda r: r["unaffected"])
    factor = hi["p50_us"] / max(lo["p50_us"], 1e-9)
    return (
        f"Streamlit rerun p50 (depth {deepest}, cached) climbs {factor:.1f}x with graph size: "
        f"{lo['p50_us'] / 1000:.2f}ms at {lo['unaffected']} unaffected nodes -> "
        f"{hi['p50_us'] / 1000:.2f}ms at {hi['unaffected']}."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Streamlit B1 (AppTest) benchmark")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    ap.add_argument("--iters", type=int, default=40)
    ap.add_argument("--warmup", type=int, default=8)
    ap.add_argument("--out", default=os.path.join(RESULTS_DIR, "b1_streamlit.csv"))
    args = ap.parse_args()

    if args.quick:
        depths, unaffected_list, iters, warmup = [1, 3, 10], [0, 64], 20, 4
    else:
        depths, unaffected_list = DEFAULT_DEPTHS, DEFAULT_UNAFFECTED
        iters, warmup = args.iters, args.warmup

    os.makedirs(RESULTS_DIR, exist_ok=True)
    print(f"B1/Streamlit sweep: rows={args.rows} depths={depths} unaffected={unaffected_list}")
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
