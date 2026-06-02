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

from golit.charts import aes, geom_line, geom_point, ggplot, ggsize, labs
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
    *,
    depth: int = 3,
) -> object:
    """Cross-framework: server-side update p50 vs unaffected nodes, one line each.

    All series are *server-side* update latency on the same dataset and affected
    depth; the x-axis is the number of unaffected nodes. Two regimes show up:

    * **Reactive** (Golit, Marimo) — flat: a slider move recomputes only its
      descendants, so cost is independent of the unaffected count.
    * **Rerun-everything** (Streamlit) — climbs: the whole script re-touches every
      node each interaction, even cached ones.

    Golit and Marimo are both flat; Marimo's floor is near raw-Polars (a thin
    reactive layer, measured at its best case — bare executor, no kernel/transport),
    while Golit's update carries content-hash memoization + the PyO3 boundary +
    fragment render. The honest picture: reactivity buys the flat curve; the floor
    is a separate axis. (AppTest/our marimo harness each add a fixed overhead that is
    *constant* in unaffected count, so the **slope** is the load-bearing comparison.)
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
    add(st_csv, "streamlit_rerun", "Streamlit (rerun everything, cached)")

    data = {"unaffected": x, "p50_ms": y, "series": series}
    title = "B1 — reactive vs rerun-everything, server-side update p50 (depth "
    plot = (
        ggplot(data, aes("unaffected", "p50_ms", color="series"))
        + geom_line(size=1.2)
        + geom_point(size=2.8)
        + labs(
            title=f"{title}{depth}, {target_rows} rows)",
            subtitle="Reactive engines (Golit, Marimo) stay flat as the graph grows; "
            "Streamlit reruns the whole script and climbs.",
            x="Unaffected nodes in the graph",
            y="Update p50 (ms)" + (", log scale" if scale_y_log10 else ""),
            color="",
        )
        + ggsize(820, 480)
    )
    if scale_y_log10 is not None:
        plot = plot + scale_y_log10()
    return plot


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

    golit_path = os.path.join(RESULTS_DIR, "b1.csv")
    st_path = os.path.join(RESULTS_DIR, "b1_streamlit.csv")
    marimo_path = os.path.join(RESULTS_DIR, "b1_marimo.csv")
    if os.path.exists(golit_path) and os.path.exists(st_path):
        marimo_csv = _load(marimo_path) if os.path.exists(marimo_path) else None
        svg = plot_to_svg(build_compare_chart(_load(golit_path), _load(st_path), marimo_csv))
        out = os.path.join(RESULTS_DIR, "b1_compare_hero.svg")
        with open(out, "w") as f:
            f.write(svg)
        tail = " (+ marimo)" if marimo_csv else ""
        print(f"Wrote {out}{tail}")
    else:
        print("skip b1_compare_hero.svg: need both b1.csv and b1_streamlit.csv")


if __name__ == "__main__":
    main()
