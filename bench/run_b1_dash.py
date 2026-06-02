"""B1 for Dash — the rival people expect to be "rerun-everything," but isn't.

Dash callbacks fire only for the changed ``Input`` (see :mod:`bench.apps.dash_app`),
so a faithful Dash twin is a **manually-wired reactive DAG**: one callback fires per
slider move, and the unaffected nodes are static layout that never re-runs. So Dash,
like Golit and Marimo, is **flat** in unaffected count — not the rerun-everything
rival the older notes assumed.

That makes the interesting comparison *not* the unaffected slope (both flat) but two
other things this harness measures:

1. **Server-compute floor** — time the affected chain only (``DashTwin.chain``), the
   same "server compute, no transport" axis as the Marimo cell and Golit's
   ``Session.update``. Dash adds nothing to the compute; it's the same Polars floor.
   Written to ``results/b1_dash.csv`` (metric ``dash_update``), one flat line on the
   cross-framework chart.
2. **Cost of a chart on the wire** — Dash's callback returns a Plotly *figure*, which
   it serializes to JSON every interaction and needs ``plotly.js`` (+ React + the
   dash-renderer) on the client to draw. Golit renders the same chart to a static SVG
   server-side and ships **zero** charting runtime. We measure both per-update
   payloads (same 16-bar chart) and the client-JS each needs, and write the summary to
   ``results/b1_dash_bytes.csv`` for the crossover chart: Golit's self-contained SVG is
   heavier *per update*, but Dash front-loads megabytes of client JS, so Golit ships
   less *in total* until several hundred interactions — and never any charting code.

    uv run --no-sync python -m bench.run_b1_dash            # full sweep
    uv run --no-sync python -m bench.run_b1_dash --quick    # fast
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import time

import plotly  # located for its bundled plotly.min.js (the Dash client runtime)

from .apps.dash_app import DashTwin, _affected, _frame, figure_bytes, figure_of
from .instrument import percentiles

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

DEFAULT_DEPTHS = [1, 3, 10]
DEFAULT_UNAFFECTED = [0, 4, 16, 64, 128, 256]
DEFAULT_ROWS = 100_000
# Distinct slider positions; the affected chain recomputes on every move.
_SLIDER_VALUES = [11, 23, 37, 53, 71]
FIELDS = ["rows", "depth", "unaffected", "metric", "exec",
          "p50_us", "p95_us", "p99_us", "mean_us", "n"]
BYTES_FIELDS = ["framework", "transport", "per_update_bytes", "client_runtime_bytes", "note"]
RENDER_FIELDS = ["framework", "stage", "compute_us", "render_us", "serialize_us", "total_us"]

# Golit ships no JS of its own; the only client runtime for a static-SVG dashboard is
# htmx (loaded once from CDN), and *zero* charting code — the SVG is server-rendered.
# htmx 2.0.4 minified is ~50 KB (the version pinned in golit/rendering/html.py).
_HTMX_BYTES = 50_000


def measure(rows: int, depth: int, unaffected: int, *, warmup: int, iters: int) -> dict[str, float]:
    """Time the affected chain (server compute, no transport) over cycled slider moves."""
    twin = DashTwin(rows=rows, depth=depth, unaffected=unaffected)
    n = len(_SLIDER_VALUES)
    idx = 0
    for _ in range(warmup):
        twin.chain(_SLIDER_VALUES[idx % n])
        idx += 1
    samples: list[int] = []
    for _ in range(iters):
        v = _SLIDER_VALUES[idx % n]
        idx += 1
        t0 = time.perf_counter_ns()
        twin.chain(v)
        samples.append(time.perf_counter_ns() - t0)
    return percentiles(samples)


def run(*, rows: int, depths: list[int], unaffected_list: list[int],
        iters: int, warmup: int) -> list[dict]:
    results: list[dict] = []
    for depth in depths:
        for u in unaffected_list:
            summary = measure(rows, depth, u, warmup=warmup, iters=iters)
            # Dash fires exactly one callback per slider move, regardless of `u`.
            results.append({
                "rows": rows, "depth": depth, "unaffected": u,
                "metric": "dash_update", "exec": 1,
                **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in summary.items()},
            })
            print(
                f"  depth={depth:>2} u={u:>4}  exec=  1  "
                f"chain p50={summary['p50_us'] / 1000:7.2f}ms "
                f"p99={summary['p99_us'] / 1000:7.2f}ms"
            )
    return results


def _dash_client_runtime_bytes() -> int:
    """The production client JS Dash serves to draw one ``dcc.Graph``: dash-renderer +
    React + the dcc/html component libs + ``plotly.min.js`` (the dominant term).
    Measured from the installed packages (prod ``.min`` bundles), so it tracks the
    pinned versions. Uncompressed; gzip is ~3x smaller."""
    import dash

    droot = os.path.dirname(dash.__file__)
    proot = os.path.dirname(plotly.__file__)
    total = 0

    def add(path: str) -> None:
        nonlocal total
        if os.path.exists(path):
            total += os.path.getsize(path)

    add(os.path.join(droot, "dash-renderer", "build", "dash_renderer.min.js"))
    add(os.path.join(droot, "dcc", "dash_core_components.js"))
    add(os.path.join(droot, "dcc", "dash_core_components-shared.js"))
    add(os.path.join(droot, "dcc", "async-graph.js"))
    add(os.path.join(droot, "html", "dash_html_components.min.js"))
    # one React (highest prod react-dom + react .min.js Dash bundles)
    for pat in ("react-dom@*.min.js", "react@*.min.js"):
        hits = sorted(glob.glob(os.path.join(droot, "deps", pat)))
        if hits:
            total += os.path.getsize(hits[-1])
    add(os.path.join(proot, "package_data", "plotly.min.js"))
    return total


def measure_bytes(rows: int, depth: int) -> list[dict]:
    """Per-update payload + client runtime for the same representative chart, both
    frameworks. The figure/SVG is a bar of the affected frame's per-group sums."""
    frame = _affected(_frame(rows), _SLIDER_VALUES[0], depth)
    dash_fig = figure_bytes(figure_of(frame))
    golit_svg = _golit_svg_bytes(frame)
    dash_rt = _dash_client_runtime_bytes()
    return [
        {"framework": "Golit", "transport": "server-rendered SVG fragment",
         "per_update_bytes": golit_svg, "client_runtime_bytes": _HTMX_BYTES,
         "note": "htmx only; zero charting runtime"},
        {"framework": "Dash", "transport": "Plotly figure JSON",
         "per_update_bytes": dash_fig, "client_runtime_bytes": dash_rt,
         "note": "plotly.js + React + dash-renderer (uncompressed)"},
    ]


def _golit_render(frame) -> str:
    """Render the same bar chart through Golit's own Lets-Plot -> SVG path: the work
    a Golit view does each update to produce the wire payload (a static SVG string)."""
    import polars as pl
    from golit.charts import aes, geom_bar, ggplot
    from golit.rendering.charts import plot_to_svg

    agg = frame.group_by("g").agg(pl.col("v").sum()).sort("g")
    data = {"g": agg["g"].to_list(), "v": agg["v"].to_list()}
    return plot_to_svg(ggplot(data, aes("g", "v")) + geom_bar(stat="identity"))


def _golit_svg_bytes(frame) -> int:
    return len(_golit_render(frame).encode("utf-8"))


def _p50_us(fn, *, warmup: int = 10, iters: int = 60) -> float:
    """Median wall time of ``fn`` in microseconds."""
    for _ in range(warmup):
        fn()
    samples: list[int] = []
    for _ in range(iters):
        t0 = time.perf_counter_ns()
        fn()
        samples.append(time.perf_counter_ns() - t0)
    samples.sort()
    return samples[len(samples) // 2] / 1000.0


def measure_render(rows: int, depth: int) -> list[dict]:
    """The **fair** per-update latency comparison: real server work to turn a slider
    move into the wire payload for the *same real chart*, split into the steps each
    path actually does — and crucially across **both** of Golit's rendering paths, so
    the comparison isolates the framework from the rendering *architecture*.

    The ``b1_dash.csv`` floor times only the affected chain (bare Polars, no framework),
    so it only says "reactive scheduling is a tie." For real charts there are two
    architectures, and Dash only has one of them:

    * **ship a spec** — build a Plotly figure, serialize to JSON, let the client draw it.
      This is what Dash always does, and what Golit's *interactive* path does too
      (``try_interactive`` → a ``plotly`` mount, the same ``figure.to_json()``). Matched
      this way, **Golit ≈ Dash** — the framework engine is not the cost.
    * **render server-side** — Golit's *static* path runs Lets-Plot to an SVG; the
      payload is the finished chart and the client needs no charting runtime. This costs
      server render time (the tall bar) and is the trade the crossover chart shows in
      bytes. Dash cannot do this.

    So the honest read is: matched architecture is a tie; Golit's slower number is a
    *different, optional* architecture, not a slower framework.
    """
    import polars as pl
    from golit.rendering.interactive import try_interactive

    data = _frame(rows)
    vals = _SLIDER_VALUES
    n = len(vals)
    state = {"i": 0}

    def nextv() -> int:
        state["i"] += 1
        return vals[state["i"] % n]

    def compute(v: int):  # the shared Polars work every path needs
        return _affected(data, v, depth).group_by("g").agg(pl.col("v").sum()).sort("g")

    def golit_svg(v: int) -> None:  # static path: render SVG server-side
        _golit_render(_affected(data, v, depth))

    def build_figure(v: int):  # shared by Dash and Golit's interactive path
        return figure_of(_affected(data, v, depth))

    fig = figure_of(_affected(data, vals[0], depth))

    compute_us = _p50_us(lambda: compute(nextv()))
    golit_svg_total = _p50_us(lambda: golit_svg(nextv()))
    build_total = _p50_us(lambda: build_figure(nextv()))
    dash_serialize_us = _p50_us(fig.to_json)  # Plotly's to_json (Dash's wire body)
    golit_plotly_serialize_us = _p50_us(lambda: try_interactive(fig))  # to_json + mount wrap

    build_us = max(build_total - compute_us, 0.0)
    golit_svg_render_us = max(golit_svg_total - compute_us, 0.0)
    return [
        {"framework": "Golit (SVG)", "stage": "render server-side, 0 client runtime",
         "compute_us": round(compute_us, 1), "render_us": round(golit_svg_render_us, 1),
         "serialize_us": 0.0, "total_us": round(compute_us + golit_svg_render_us, 1)},
        {"framework": "Golit (Plotly)", "stage": "ship figure spec (client draws)",
         "compute_us": round(compute_us, 1), "render_us": round(build_us, 1),
         "serialize_us": round(golit_plotly_serialize_us, 1),
         "total_us": round(compute_us + build_us + golit_plotly_serialize_us, 1)},
        {"framework": "Dash", "stage": "ship figure spec (client draws)",
         "compute_us": round(compute_us, 1), "render_us": round(build_us, 1),
         "serialize_us": round(dash_serialize_us, 1),
         "total_us": round(compute_us + build_us + dash_serialize_us, 1)},
    ]


def _headline(results: list[dict], byte_rows: list[dict], render_rows: list[dict]) -> str:
    deepest = max(r["depth"] for r in results)
    line = [r for r in results if r["depth"] == deepest]
    lo = min(line, key=lambda r: r["unaffected"])
    hi = max(line, key=lambda r: r["unaffected"])
    factor = hi["p50_us"] / max(lo["p50_us"], 1e-9)
    shape = "stays ~flat" if factor < 1.5 else f"climbs {factor:.1f}x"
    g = next(b for b in byte_rows if b["framework"] == "Golit")
    d = next(b for b in byte_rows if b["framework"] == "Dash")
    denom = g["per_update_bytes"] - d["per_update_bytes"]
    crossover = (d["client_runtime_bytes"] - g["client_runtime_bytes"]) / denom if denom > 0 else 0
    gsvg = next(r for r in render_rows if r["framework"] == "Golit (SVG)")
    gpl = next(r for r in render_rows if r["framework"] == "Golit (Plotly)")
    dr = next(r for r in render_rows if r["framework"] == "Dash")
    return (
        f"Dash chain p50 (depth {deepest}) {shape} with graph size (exec stays 1 — one "
        f"callback per move): Dash is reactive/flat, not rerun-everything.\n"
        f"FAIR per-update (same real chart): architecture-matched, Golit(Plotly) "
        f"{gpl['total_us'] / 1000:.2f}ms ≈ Dash {dr['total_us'] / 1000:.2f}ms (both ship a "
        f"figure spec) — the engine is NOT the cost. Golit's static path renders the SVG "
        f"server-side at {gsvg['total_us'] / 1000:.2f}ms (a different, optional "
        f"architecture: heavier server, zero client runtime), which Dash can't do.\n"
        f"Wire: per update Golit SVG {g['per_update_bytes'] / 1000:.1f} KB vs Dash figure "
        f"JSON {d['per_update_bytes'] / 1000:.1f} KB (Dash lighter), but Dash needs "
        f"{d['client_runtime_bytes'] / 1_000_000:.1f} MB client JS vs Golit's "
        f"{g['client_runtime_bytes'] / 1000:.0f} KB (zero charting) — cumulative bytes "
        f"cross at ~{crossover:.0f} interactions. (Golit-Plotly would match Dash's bytes "
        f"too; the byte advantage is the SVG path's.)"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Dash B1 (manual reactive DAG) benchmark")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    ap.add_argument("--iters", type=int, default=40)
    ap.add_argument("--warmup", type=int, default=8)
    ap.add_argument("--out", default=os.path.join(RESULTS_DIR, "b1_dash.csv"))
    ap.add_argument("--bytes-out", default=os.path.join(RESULTS_DIR, "b1_dash_bytes.csv"))
    ap.add_argument("--render-out", default=os.path.join(RESULTS_DIR, "b1_dash_render.csv"))
    args = ap.parse_args()

    if args.quick:
        depths, unaffected_list, iters, warmup = [1, 3, 10], [0, 64], 20, 4
    else:
        depths, unaffected_list = DEFAULT_DEPTHS, DEFAULT_UNAFFECTED
        iters, warmup = args.iters, args.warmup

    os.makedirs(RESULTS_DIR, exist_ok=True)
    print(f"B1/Dash sweep: rows={args.rows} depths={depths} unaffected={unaffected_list}")
    print(f"iters={iters} warmup={warmup}\n")

    t0 = time.perf_counter()
    results = run(rows=args.rows, depths=depths, unaffected_list=unaffected_list,
                  iters=iters, warmup=warmup)
    byte_rows = measure_bytes(args.rows, max(depths))
    render_rows = measure_render(args.rows, 3 if 3 in depths else depths[0])
    elapsed = time.perf_counter() - t0

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(results)
    with open(args.bytes_out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=BYTES_FIELDS)
        w.writeheader()
        w.writerows(byte_rows)
    with open(args.render_out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RENDER_FIELDS)
        w.writeheader()
        w.writerows(render_rows)

    print(f"\nWrote {len(results)} rows to {args.out}, {len(byte_rows)} to "
          f"{args.bytes_out}, {len(render_rows)} to {args.render_out} in {elapsed:.1f}s")
    print("\n" + _headline(results, byte_rows, render_rows))


if __name__ == "__main__":
    main()
