"""B1 for Marimo — reactive partial-rerun latency, the reactive-vs-reactive rival.

Marimo shares Golit's thesis: a UI change re-runs only the cells that transitively
depend on it, not the whole script. So the fair measurement is **not** ``app.run()``
(that reruns everything — that would be the Streamlit story). Instead we drive
marimo's own reactive machinery headless:

* ``dataflow.transitive_closure`` — marimo's real scheduler: the descendants of the
  slider's cell. This *is* marimo's dirty subgraph, the analog of Golit's Rust
  ``dirty_subgraph``. It returns exactly ``depth + 1`` cells (the affected chain +
  chart) regardless of how many unaffected cells exist — the integer proof, from
  marimo's own graph.
* ``dataflow.topological_sort`` — order that dirty set.
* ``executor.execute_cell`` — marimo's real per-cell executor, run over just that set.

We time ``slider._update(v)`` (marimo's UI value-set path) + scheduling + execution —
i.e. *decide what to run, then run it*, exactly the server-side work Golit's
``Session.update`` does. Like the in-process Golit number and the Streamlit
``AppTest`` number, this excludes the browser websocket; it's server compute, the
same axis. The harness installs a marimo *script context* (``NoopStream``), so no
kernel messaging overhead is charged either — the rival's best case.

    uv run --no-sync python -m bench.run_b1_marimo            # full sweep
    uv run --no-sync python -m bench.run_b1_marimo --quick    # fast
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import tempfile
import time
from typing import Any

from marimo._ast.app import InternalApp
from marimo._ast.load import load_app
from marimo._messaging.types import NoopStream
from marimo._runtime import dataflow
from marimo._runtime.context.script_context import initialize_script_context
from marimo._runtime.context.types import (
    get_context,
    runtime_context_installed,
    teardown_context,
)
from marimo._runtime.executor import ExecutionConfig, get_executor
from marimo._runtime.patches import create_main_module

from .apps.marimo_gen import notebook_source
from .instrument import percentiles

logging.getLogger("marimo").setLevel(logging.ERROR)

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

DEFAULT_DEPTHS = [1, 3, 10]
DEFAULT_UNAFFECTED = [0, 4, 16, 64, 128, 256]
DEFAULT_ROWS = 100_000
# Distinct slider positions; the affected chain recomputes every move regardless.
_SLIDER_VALUES = [11, 23, 37, 53, 71]
FIELDS = ["rows", "depth", "unaffected", "metric", "exec",
          "p50_us", "p95_us", "p99_us", "mean_us", "n"]


class _Session:
    """A loaded marimo notebook with its context installed and globals warmed.

    Holds marimo's real graph, executor, and the live slider object, plus the id of
    the slider's cell so ``transitive_closure`` can recompute the dirty set per move.
    """

    def __init__(self, rows: int, depth: int, unaffected: int) -> None:
        src = notebook_source(rows=rows, depth=depth, unaffected=unaffected)
        fd, self.path = tempfile.mkstemp(suffix=".py", prefix="golit_bench_marimo_")
        with os.fdopen(fd, "w") as f:
            f.write(src)

        app = load_app(self.path)
        if app is None:
            raise RuntimeError("marimo load_app returned None")
        iapp = InternalApp(app)
        self.graph = iapp.graph

        # Script context is thread-local and installed once; tear down any prior
        # config's context so each notebook starts clean.
        if runtime_context_installed():
            teardown_context()
        initialize_script_context(app=iapp, stream=NoopStream(), filename=None)
        self.ctx = get_context()

        module = create_main_module(file=None, input_override=None, print_override=None)
        self.glbls: dict[str, Any] = module.__dict__
        self.executor = get_executor(ExecutionConfig())

        # Initial render: run every cell once to populate globals (data, slider, …).
        for cid in dataflow.topological_sort(self.graph, set(self.graph.cells.keys())):
            with self.ctx.with_cell_id(cid):
                self.executor.execute_cell(self.graph.cells[cid], self.glbls, self.graph)

        self.slider_cid = self._cell_defining("threshold")
        self.slider = self.glbls["threshold"]

    def _cell_defining(self, name: str) -> Any:
        for cid, cell in self.graph.cells.items():
            if name in cell.defs:
                return cid
        raise KeyError(name)

    def update(self, value: int) -> int:
        """Marimo's reactive update: set the slider, reschedule, run the dirty set.

        Returns the number of cells executed (marimo's dirty subgraph size).
        """
        self.slider._update(value)
        dirty = dataflow.transitive_closure(
            self.graph, {self.slider_cid}, children=True, inclusive=False
        )
        order = dataflow.topological_sort(self.graph, dirty)
        for cid in order:
            with self.ctx.with_cell_id(cid):
                self.executor.execute_cell(self.graph.cells[cid], self.glbls, self.graph)
        return len(order)

    def close(self) -> None:
        try:
            os.unlink(self.path)
        except OSError:
            pass


def measure(
    rows: int, depth: int, unaffected: int, *, warmup: int, iters: int
) -> tuple[dict[str, float], int]:
    sess = _Session(rows, depth, unaffected)
    try:
        n = len(_SLIDER_VALUES)
        idx = 0
        for _ in range(warmup):
            sess.update(_SLIDER_VALUES[idx % n])
            idx += 1

        samples: list[int] = []
        exec_count = 0
        for _ in range(iters):
            v = _SLIDER_VALUES[idx % n]
            idx += 1
            t0 = time.perf_counter_ns()
            ran = sess.update(v)
            samples.append(time.perf_counter_ns() - t0)
            exec_count = max(exec_count, ran)
        return percentiles(samples), exec_count
    finally:
        sess.close()


def run(*, rows: int, depths: list[int], unaffected_list: list[int],
        iters: int, warmup: int) -> list[dict]:
    results: list[dict] = []
    for depth in depths:
        for u in unaffected_list:
            summary, exec_count = measure(rows, depth, u, warmup=warmup, iters=iters)
            results.append({
                "rows": rows, "depth": depth, "unaffected": u,
                "metric": "marimo_rerun", "exec": exec_count,
                **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in summary.items()},
            })
            print(
                f"  depth={depth:>2} u={u:>4}  exec={exec_count:>3}  "
                f"rerun p50={summary['p50_us'] / 1000:7.2f}ms "
                f"p99={summary['p99_us'] / 1000:7.2f}ms"
            )
    return results


def _headline(results: list[dict]) -> str:
    deepest = max(r["depth"] for r in results)
    line = [r for r in results if r["depth"] == deepest]
    lo = min(line, key=lambda r: r["unaffected"])
    hi = max(line, key=lambda r: r["unaffected"])
    factor = hi["p50_us"] / max(lo["p50_us"], 1e-9)
    shape = "stays ~flat" if factor < 1.5 else f"climbs {factor:.1f}x"
    return (
        f"Marimo reactive rerun p50 (depth {deepest}) {shape} with graph size: "
        f"{lo['p50_us'] / 1000:.2f}ms at {lo['unaffected']} unaffected nodes -> "
        f"{hi['p50_us'] / 1000:.2f}ms at {hi['unaffected']} (exec stays {hi['exec']})."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Marimo B1 (reactive partial-rerun) benchmark")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    ap.add_argument("--iters", type=int, default=40)
    ap.add_argument("--warmup", type=int, default=8)
    ap.add_argument("--out", default=os.path.join(RESULTS_DIR, "b1_marimo.csv"))
    args = ap.parse_args()

    if args.quick:
        depths, unaffected_list, iters, warmup = [1, 3, 10], [0, 64], 20, 4
    else:
        depths, unaffected_list = DEFAULT_DEPTHS, DEFAULT_UNAFFECTED
        iters, warmup = args.iters, args.warmup

    os.makedirs(RESULTS_DIR, exist_ok=True)
    print(f"B1/Marimo sweep: rows={args.rows} depths={depths} unaffected={unaffected_list}")
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
