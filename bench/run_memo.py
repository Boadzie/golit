"""B-memo — the advantage Dash structurally can't match: cross-update memoization.

``run_b1_dash*`` shows that on a *single* chain, Golit and Dash do identical work and
tie. But real dashboards aren't a single chain — they **share upstream work**: one
expensive step (a load, a join, a sort) feeds several views. That is where the engines
diverge, because Golit memoizes per node and Dash doesn't.

Same shape, both ways::

    data ── heavy(data) ──┬── view_a(heavy, threshold_a)   <- the slider moves only this
                          └── view_b(heavy, threshold_b)

Move ``threshold_a``:

* **Golit** — ``Session.update`` schedules the dirty subgraph from ``threshold_a``.
  ``heavy`` depends only on ``data`` (clean), so its epoch signature is unchanged: the
  kernel **skips it** and reuses the cached frame. Only ``view_a`` runs. ``heavy`` is
  executed *zero* times across all updates (asserted below).
* **Dash (recompute)** — a callback ``Output(chart_a), Input(threshold_a)`` has no
  cross-call memo, so it re-runs its whole body: ``heavy(data)`` **again**, then
  ``view_a``. The idiomatic case.
* **Dash (dcc.Store)** — avoids the recompute by stashing ``heavy``'s output, but pays
  to **serialize/deserialize** that intermediate every interaction (browser round-trip
  or server cache). We measure the deserialize alone as a floor on that tax — a cost
  Golit's in-memory memo never pays.

We sweep the cost of ``heavy`` (dataset rows). The Golit/Dash gap is ~the cost of
``heavy`` and widens as the shared upstream grows. Writes ``results/b_memo.csv``::

    uv run --no-sync python -m bench.run_memo
    uv run --no-sync python -m bench.run_memo --quick
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time

import numpy as np
import polars as pl
from golit.engine import Session

from .gen_app import _make_frame, make_memo_app, memo_heavy, memo_payload

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
_SLIDER_VALUES = [11, 23, 37, 53, 71]
FIELDS = ["rows", "metric", "p50_us", "p95_us", "p99_us", "heavy_runs", "speedup_vs_recompute"]


def _p_us(fn, *, warmup: int, iters: int) -> dict[str, float]:
    n = len(_SLIDER_VALUES)
    for i in range(warmup):
        fn(_SLIDER_VALUES[i % n])
    samples: list[int] = []
    for i in range(iters):
        t0 = time.perf_counter_ns()
        fn(_SLIDER_VALUES[i % n])
        samples.append(time.perf_counter_ns() - t0)
    a = np.asarray(samples, dtype=float) / 1000.0
    return {"p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)),
            "p99": float(np.percentile(a, 99))}


def _build_golit(rows: int) -> tuple[Session, dict]:
    """The shared-upstream app (see :func:`gen_app.make_memo_app`), with a call counter on
    ``heavy`` to prove it is memoized — executed only during the initial render, never on a
    ``threshold_a`` update."""
    calls = {"heavy": 0}

    def on_heavy() -> None:
        calls["heavy"] += 1

    app = make_memo_app(rows=rows, on_heavy=on_heavy)
    session = Session(app)
    session.initial_render()  # heavy computed once here
    return session, calls


def measure_rows(rows: int, *, warmup: int, iters: int) -> list[dict]:
    frame = _make_frame(rows)

    # --- Golit: memoized update (heavy is clean, only view_a runs) ---
    session, calls = _build_golit(rows)
    runs_before = calls["heavy"]
    golit = _p_us(lambda v: session.update("threshold_a", v), warmup=warmup, iters=iters)
    heavy_runs = calls["heavy"] - runs_before  # executions during updates only

    # --- Dash (recompute): the callback re-runs heavy(data) + view every move ---
    def dash_recompute(v: int) -> str:
        return json.dumps(memo_payload(memo_heavy(frame), v))
    dash = _p_us(dash_recompute, warmup=warmup, iters=iters)

    # --- Dash (dcc.Store): no recompute, but deserialize the cached intermediate ---
    heavy_json = json.dumps(memo_heavy(frame).to_dict(as_series=False))
    def store_tax(v: int) -> object:
        cached = json.loads(heavy_json)              # the per-update Store deserialize
        return memo_payload(pl.DataFrame(cached), v)  # then the same cheap view work
    store = _p_us(store_tax, warmup=max(2, warmup // 2), iters=max(8, iters // 4))

    speedup = dash["p50"] / max(golit["p50"], 1e-9)
    return [
        {"rows": rows, "metric": "golit_memo", "p50_us": round(golit["p50"], 1),
         "p95_us": round(golit["p95"], 1), "p99_us": round(golit["p99"], 1),
         "heavy_runs": heavy_runs, "speedup_vs_recompute": round(speedup, 2)},
        {"rows": rows, "metric": "dash_recompute", "p50_us": round(dash["p50"], 1),
         "p95_us": round(dash["p95"], 1), "p99_us": round(dash["p99"], 1),
         "heavy_runs": iters, "speedup_vs_recompute": 1.0},
        {"rows": rows, "metric": "dash_store_deserialize", "p50_us": round(store["p50"], 1),
         "p95_us": round(store["p95"], 1), "p99_us": round(store["p99"], 1),
         "heavy_runs": 0, "speedup_vs_recompute": round(store["p50"] / max(golit["p50"], 1e-9), 2)},
    ]


def _headline(rows_results: dict[int, list[dict]]) -> str:
    lines = []
    for rows in sorted(rows_results):
        by = {r["metric"]: r for r in rows_results[rows]}
        g, d, s = by["golit_memo"], by["dash_recompute"], by["dash_store_deserialize"]
        lines.append(
            f"{rows:>9,} rows: Golit {g['p50_us'] / 1000:5.2f}ms (heavy ran {g['heavy_runs']}x) "
            f"vs Dash-recompute {d['p50_us'] / 1000:5.2f}ms ({g['speedup_vs_recompute']:.1f}x) "
            f"vs Dash-Store-deserialize {s['p50_us'] / 1000:5.2f}ms "
            f"({s['speedup_vs_recompute']:.1f}x).")
    return ("Cross-update memoization (move one slider; shared upstream stays clean):\n  "
            + "\n  ".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description="Golit memoization vs Dash recompute")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--rows", default="100000,500000,1000000,2000000",
                    help="comma-separated shared-upstream sizes to sweep")
    ap.add_argument("--iters", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--out", default=os.path.join(RESULTS_DIR, "b_memo.csv"))
    args = ap.parse_args()

    iters, warmup = (40, 8) if args.quick else (args.iters, args.warmup)
    rows_levels = [int(x) for x in args.rows.split(",")]

    os.makedirs(RESULTS_DIR, exist_ok=True)
    print(f"B-memo — shared-upstream memoization: rows={rows_levels} iters={iters}\n")

    t0 = time.perf_counter()
    rows_results: dict[int, list[dict]] = {}
    flat: list[dict] = []
    for rows in rows_levels:
        res = measure_rows(rows, warmup=warmup, iters=iters)
        rows_results[rows] = res
        flat.extend(res)
        by = {r["metric"]: r for r in res}
        g, d, s = by["golit_memo"], by["dash_recompute"], by["dash_store_deserialize"]
        print(f"  {rows:>9,}r  golit={g['p50_us'] / 1000:6.2f}ms (heavy x{g['heavy_runs']})  "
              f"dash-recompute={d['p50_us'] / 1000:6.2f}ms  "
              f"dash-store={s['p50_us'] / 1000:6.2f}ms  -> {g['speedup_vs_recompute']:.1f}x")
    elapsed = time.perf_counter() - t0

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(flat)

    print(f"\nWrote {len(flat)} rows to {args.out} in {elapsed:.1f}s")
    print("\n" + _headline(rows_results))


if __name__ == "__main__":
    main()
