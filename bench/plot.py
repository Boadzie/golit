"""Render B1's hero chart from ``bench/results/b1.csv``.

The decisive plot (``golit_benchmark.md``): **update latency vs number of
unaffected nodes**. Golit's update lines stay flat near the floor while the
"full recompute" line climbs — *cost ∝ change*, drawn in one picture. Dogfoods
Golit's own Lets-Plot → static-SVG path (no client runtime), so the benchmark
chart is rendered the same way the framework renders charts.

    uv run --no-sync python -m bench.plot
"""

from __future__ import annotations

import csv
import os

from golit.charts import aes, geom_bar, geom_line, geom_point, ggplot, ggsize, labs
from golit.rendering.charts import plot_to_svg

try:  # log scale lives in the lets_plot namespace re-exported by golit.charts
    from golit.charts import scale_y_log10
except ImportError:  # pragma: no cover - older lets-plot
    scale_y_log10 = None  # type: ignore[assignment]

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def _load(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def build_chart(rows_csv: list[dict]) -> object:
    # Hero chart uses the dataset size the full-recompute baseline was measured at.
    full_rows = {r["rows"] for r in rows_csv if r["metric"] == "full"}
    target_rows = max(full_rows, key=int) if full_rows else max(r["rows"] for r in rows_csv)

    x: list[int] = []
    y: list[float] = []
    series: list[str] = []
    for r in rows_csv:
        if r["rows"] != target_rows:
            continue
        if r["metric"] == "update":
            label = f"update (depth {r['depth']})"
        elif r["metric"] == "full":
            label = "full recompute (rerun everything)"
        else:
            continue
        x.append(int(r["unaffected"]))
        y.append(float(r["p99_us"]))
        series.append(label)

    data = {"unaffected": x, "p99_us": y, "series": series}
    plot = (
        ggplot(data, aes("unaffected", "p99_us", color="series"))
        + geom_line(size=1.1)
        + geom_point(size=2.6)
        + labs(
            title=f"B1 — update p99 vs unaffected nodes (dataset = {target_rows} rows)",
            subtitle="Golit update cost stays flat as the graph grows; full recompute climbs.",
            x="Unaffected nodes in the graph",
            y="Update p99 (µs)" + (", log scale" if scale_y_log10 else ""),
            color="",
        )
        + ggsize(780, 470)
    )
    if scale_y_log10 is not None:
        plot = plot + scale_y_log10()
    return plot


def build_http_chart(rows_csv: list[dict]) -> object:
    """End-to-end (HTTP) update p99 vs unaffected nodes, one flat line per depth.

    No climbing baseline here — the point is that the flat curve *survives real
    transport*, so a linear y-axis (in ms) shows the flatness most honestly.
    """
    target_rows = max((r["rows"] for r in rows_csv), key=int)
    x: list[int] = []
    y: list[float] = []
    series: list[str] = []
    for r in rows_csv:
        if r["rows"] != target_rows:
            continue
        x.append(int(r["unaffected"]))
        y.append(float(r["p99_us"]) / 1000.0)  # us -> ms
        series.append(f"end-to-end (depth {r['depth']})")

    data = {"unaffected": x, "p99_ms": y, "series": series}
    return (
        ggplot(data, aes("unaffected", "p99_ms", color="series"))
        + geom_line(size=1.1)
        + geom_point(size=2.6)
        + labs(
            title=f"B1 over HTTP — end-to-end update p99 (dataset = {target_rows} rows)",
            subtitle="Flat over real transport; 177 B/update, no client runtime.",
            x="Unaffected nodes in the graph",
            y="End-to-end update p99 (ms)",
            color="",
        )
        + ggsize(780, 470)
    )


def build_compare_chart(
    golit_csv: list[dict],
    st_csv: list[dict],
    marimo_csv: list[dict] | None = None,
    dash_csv: list[dict] | None = None,
    *,
    depth: int = 3,
) -> object:
    """Cross-framework: server-side update p50 vs unaffected nodes, one line each.

    All series are *server-side* update latency on the same dataset and affected
    depth; the x-axis is the number of unaffected nodes. Two regimes show up:

    * **Reactive** (Golit, Marimo, Dash) — flat: a slider move recomputes only its
      dependents, so cost is independent of the unaffected count. Dash earns this the
      same way Golit and Marimo do — its callbacks fire only for the changed Input
      (it is a *manually*-wired reactive DAG), so it is **not** a rerun-everything
      rival; the unaffected nodes are static layout it never re-touches.
    * **Rerun-everything** (Streamlit) — climbs: the whole script re-touches every
      node each interaction, even cached ones.

    All three reactive engines sit near the raw-Polars floor (the affected chain is
    the same Polars work); the load-bearing comparison is the **slope** — flat vs
    climbing. (AppTest/our marimo+dash harnesses each add a fixed overhead constant in
    unaffected count.) Where Golit and Dash actually diverge is the wire, a separate
    axis — see :func:`build_crossover_chart`.
    """
    target_rows = max((r["rows"] for r in st_csv), key=int)
    x: list[int] = []
    y: list[float] = []
    series: list[str] = []

    def add(rows_csv, metric, label):
        for r in rows_csv:
            if r["metric"] == metric and r["rows"] == target_rows and int(r["depth"]) == depth:
                x.append(int(r["unaffected"]))
                y.append(float(r["p50_us"]) / 1000.0)
                series.append(label)

    add(golit_csv, "update", "Golit (reactive, dirty subgraph)")
    if marimo_csv:
        add(marimo_csv, "marimo_rerun", "Marimo (reactive, descendant rerun)")
    if dash_csv:
        add(dash_csv, "dash_update", "Dash (reactive, manual callback DAG)")
    add(st_csv, "streamlit_rerun", "Streamlit (rerun everything, cached)")

    data = {"unaffected": x, "p50_ms": y, "series": series}
    title = "B1 — reactive vs rerun-everything, server-side update p50 (depth "
    plot = (
        ggplot(data, aes("unaffected", "p50_ms", color="series"))
        + geom_line(size=1.2)
        + geom_point(size=2.8)
        + labs(
            title=f"{title}{depth}, {target_rows} rows)",
            subtitle="Reactive engines (Golit, Marimo, Dash) stay flat as the graph "
            "grows; Streamlit reruns the whole script and climbs.",
            x="Unaffected nodes in the graph",
            y="Update p50 (ms)" + (", log scale" if scale_y_log10 else ""),
            color="",
        )
        + ggsize(820, 480)
    )
    if scale_y_log10 is not None:
        plot = plot + scale_y_log10()
    return plot


def build_crossover_chart(byte_rows: list[dict]) -> object:
    """Golit vs Dash — cumulative bytes to the client over a session (same chart).

    The reactive floor is a tie (both flat, both at the Polars floor); the real
    Golit/Dash split is the wire. Dash front-loads its client runtime — plotly.js +
    React + the dash-renderer, megabytes — then sends a compact figure-JSON diff per
    interaction. Golit ships a self-contained server-rendered SVG each update (heavier
    per move) and **no** charting runtime. So per update Dash is lighter, but
    cumulative bytes ``runtime + per_update * N`` start far apart: Golit ships less in
    total until the lines cross, a few hundred interactions in — and never any
    charting code. This plots both lines so the crossover is explicit, not asserted.
    """
    by = {r["framework"]: r for r in byte_rows}
    g, d = by["Golit"], by["Dash"]
    g_run, g_step = float(g["client_runtime_bytes"]), float(g["per_update_bytes"])
    d_run, d_step = float(d["client_runtime_bytes"]), float(d["per_update_bytes"])

    denom = g_step - d_step
    crossover = (d_run - g_run) / denom if denom > 0 else 0.0
    n_max = max(int(crossover * 2), 200)
    xs = [round(n_max * i / 40) for i in range(41)]

    x: list[int] = []
    y: list[float] = []
    series: list[str] = []
    g_label = "Golit (server SVG, 0 charting JS)"
    d_label = "Dash (figure JSON + ~%.1f MB client JS)" % (d_run / 1_000_000)
    for n in xs:
        x.append(n)
        y.append((g_run + g_step * n) / 1_000_000)
        series.append(g_label)
        x.append(n)
        y.append((d_run + d_step * n) / 1_000_000)
        series.append(d_label)

    data = {"interactions": x, "cumulative_mb": y, "series": series}
    return (
        ggplot(data, aes("interactions", "cumulative_mb", color="series"))
        + geom_line(size=1.2)
        + labs(
            title="Golit vs Dash — cumulative bytes over a session (same chart)",
            subtitle=f"Dash front-loads ~{d_run / 1_000_000:.1f} MB of client JS then "
            f"sends light diffs; Golit ships a self-contained SVG and no charting "
            f"runtime. Crossover ≈ {crossover:.0f} interactions.",
            x="Slider interactions in the session",
            y="Cumulative bytes to the client (MB, uncompressed)",
            color="",
        )
        + ggsize(820, 480)
    )


def build_render_chart(render_rows: list[dict]) -> object:
    """Golit vs Dash — per-update *server* work for the same real chart, broken into
    stages. The fair latency comparison (``b1_dash.csv`` times only the bare-Polars
    chain, no framework). Both pay the same shared compute; then Golit renders the SVG
    server-side while Dash builds a figure spec and serializes it for the client to
    draw. Golit's taller bar is the server-render cost — the same trade the crossover
    chart shows in bytes: Golit does more on the server so the client gets a
    self-contained chart and no charting runtime.
    """
    stages = [("compute", "compute_us"), ("render", "render_us"), ("serialize", "serialize_us")]
    x: list[str] = []
    y: list[float] = []
    stage: list[str] = []
    for r in render_rows:
        for label, key in stages:
            val = float(r[key])
            if val <= 0:
                continue
            x.append(r["framework"])
            y.append(val / 1000.0)
            stage.append(label)

    data = {"framework": x, "ms": y, "stage": stage}
    return (
        ggplot(data, aes("framework", "ms", fill="stage"))
        + geom_bar(stat="identity")
        + labs(
            title="Golit vs Dash — per-update server work for the same chart (100K rows, depth 3)",
            subtitle="Fair test: both render a real chart. Golit renders the SVG "
            "server-side (heavier server, zero client runtime); Dash ships a figure "
            "spec the client draws (lighter server, but ~5.9 MB client JS).",
            x="",
            y="Per-update server time (ms)",
            fill="",
        )
        + ggsize(720, 470)
    )


def build_b2_saturation_chart(rows_csv: list[dict]) -> object:
    """B2 single-instance load curve: end-to-end p99 vs achieved throughput.

    Each point is a concurrency level on one instance. The curve rises gently,
    then hooks sharply upward where the instance saturates (~4000 req/s): past
    that knee, more concurrency buys no throughput, only queueing latency. That
    knee is one core's worth of serial ``session.update`` — the update runs inline
    on the event loop, so a single worker is CPU-bound on compute, not I/O.
    """
    conc = [r for r in rows_csv if r["phase"] == "concurrency"]
    conc.sort(key=lambda r: int(r["concurrency"]))
    x = [float(r["throughput_rps"]) for r in conc]
    y = [float(r["p99_us"]) / 1000.0 for r in conc]
    labels = [f"C={r['concurrency']}" for r in conc]
    data = {"throughput_rps": x, "p99_ms": y, "C": labels}
    return (
        ggplot(data, aes("throughput_rps", "p99_ms"))
        + geom_line(size=1.2, color="#2563eb")
        + geom_point(size=2.8, color="#2563eb")
        + labs(
            title="B2 — single-instance load curve (100K rows, depth 3)",
            subtitle="Each point is a concurrency level. The curve hooks up where one "
            "instance saturates (~4000 req/s) — past the knee, only latency grows.",
            x="Achieved throughput (req/s)",
            y="End-to-end update p99 (ms)",
        )
        + ggsize(800, 470)
    )


def build_b2_scaling_chart(rows_csv: list[dict]) -> object:
    """B2 horizontal scaling: throughput vs sticky instances, achieved vs ideal.

    Fixed saturating load, sessions pinned to instances by cookie hash (Golit
    keeps state worker-local, so this is its scale model). Throughput rises with
    instance count; the dashed line is perfect linear scaling off the single
    instance. The achieved/ideal gap is honest — on one host the N servers and
    the load generator share the same cores, so linear scaling needs separate
    machines, not a busier laptop.
    """
    scaling = [r for r in rows_csv if r["phase"] == "scaling"]
    scaling.sort(key=lambda r: int(r["instances"]))
    base = float(scaling[0]["throughput_rps"]) if scaling else 0.0

    x: list[int] = []
    y: list[float] = []
    series: list[str] = []
    for r in scaling:
        n = int(r["instances"])
        x.append(n)
        y.append(float(r["throughput_rps"]))
        series.append("achieved")
        x.append(n)
        y.append(base * n)
        series.append("ideal (linear)")

    data = {"instances": x, "throughput_rps": y, "series": series}
    return (
        ggplot(data, aes("instances", "throughput_rps", color="series"))
        + geom_line(size=1.2)
        + geom_point(size=2.8)
        + labs(
            title="B2 — horizontal scaling under sticky sessions (C=32, 100K rows)",
            subtitle="Throughput rises with instances; gap to linear is one-host core "
            "contention (servers + load generator share the box), not the scale model.",
            x="Sticky instances",
            y="Achieved throughput (req/s)",
            color="",
        )
        + ggsize(800, 470)
    )


def _render(build, csv_name: str, out_name: str, hint: str) -> None:
    csv_path = os.path.join(RESULTS_DIR, csv_name)
    if not os.path.exists(csv_path):
        print(f"skip {out_name}: no {csv_name} (run `{hint}`)")
        return
    svg = plot_to_svg(build(_load(csv_path)))
    out = os.path.join(RESULTS_DIR, out_name)
    with open(out, "w") as f:
        f.write(svg)
    print(f"Wrote {out}")


def main() -> None:
    _render(build_chart, "b1.csv", "b1_hero.svg", "python -m bench.run_b1")
    _render(build_http_chart, "b1_http.csv", "b1_http_hero.svg",
            "python -m bench.http.run_b1_http")
    _render(build_b2_saturation_chart, "b2.csv", "b2_saturation.svg",
            "python -m bench.http.run_b2")
    _render(build_b2_scaling_chart, "b2.csv", "b2_scaling.svg",
            "python -m bench.http.run_b2")
    _render(build_crossover_chart, "b1_dash_bytes.csv", "b1_dash_crossover.svg",
            "python -m bench.run_b1_dash")
    _render(build_render_chart, "b1_dash_render.csv", "b1_dash_render.svg",
            "python -m bench.run_b1_dash")

    golit_path = os.path.join(RESULTS_DIR, "b1.csv")
    st_path = os.path.join(RESULTS_DIR, "b1_streamlit.csv")
    marimo_path = os.path.join(RESULTS_DIR, "b1_marimo.csv")
    dash_path = os.path.join(RESULTS_DIR, "b1_dash.csv")
    if os.path.exists(golit_path) and os.path.exists(st_path):
        marimo_csv = _load(marimo_path) if os.path.exists(marimo_path) else None
        dash_csv = _load(dash_path) if os.path.exists(dash_path) else None
        svg = plot_to_svg(
            build_compare_chart(_load(golit_path), _load(st_path), marimo_csv, dash_csv)
        )
        out = os.path.join(RESULTS_DIR, "b1_compare_hero.svg")
        with open(out, "w") as f:
            f.write(svg)
        extras = [(" +marimo", marimo_csv), (" +dash", dash_csv)]
        tail = "".join(t for t, present in extras if present)
        print(f"Wrote {out}{tail}")
    else:
        print("skip b1_compare_hero.svg: need both b1.csv and b1_streamlit.csv")


if __name__ == "__main__":
    main()
