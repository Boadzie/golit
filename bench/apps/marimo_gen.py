"""Generate the Marimo notebook that is the behavioral twin of the Golit app.

Marimo is the rival that *shares Golit's thesis*: it is a reactive notebook, so a
slider move re-runs only the cells that transitively depend on the slider — not the
whole script (that's Streamlit). Including it is non-negotiable; it's the
reactive-vs-reactive comparison, the one that actually tests Golit's floor rather
than just "reactive beats rerun-everything."

The notebook has the same shape as :func:`bench.gen_app.make_app` and the Streamlit
twin:

    data ─┬─> r0(threshold) ─> r1 ─> … ─> r{depth-1} ─> chart   (affected chain)
          ├─> u0  ┐
          └─> …   ┘  unaffected cells — depend only on `data`

Each node is a marimo cell. ``data`` and every ``u*`` reference only ``data`` (and
``pl``), so they are **not** descendants of the slider's cell; the affected chain
references ``threshold`` and so is. That partition is computed by *marimo's own*
dataflow graph — see :mod:`bench.run_b1_marimo`, which drives marimo's real
scheduler (``transitive_closure``) and real executor (``execute_cell``) to recompute
exactly that dirty set, the same axis as Golit's in-process ``Session.update``.

The graph shape is baked into the generated source (one notebook per config), so the
result is a genuine marimo notebook a user could open with ``marimo edit``. Run this
module to print a representative one:

    uv run --no-sync python -m bench.apps.marimo_gen --depth 3 --unaffected 4
"""

from __future__ import annotations


def notebook_source(*, rows: int, depth: int, unaffected: int) -> str:
    """Return marimo notebook source for the given graph shape."""
    if depth < 1:
        raise ValueError("depth must be >= 1")
    out: list[str] = ["import marimo", "", "app = marimo.App()", ""]

    def cell(args: str, body: list[str]) -> None:
        out.append("@app.cell")
        out.append(f"def _({args}):")
        out.extend("    " + line for line in body)
        out.append("")

    # Imports cell — marimo cell-local vars (leading underscore) stay out of the graph.
    cell("", [
        "import marimo as mo",
        "import numpy as np",
        "import polars as pl",
        "return mo, np, pl",
    ])
    # Source: no slider reference, so a slider move never dirties it (stays warm).
    cell("np, pl", [
        "_rng = np.random.default_rng(0)",
        f"_v = _rng.integers(0, 100, size={rows})",
        '_df = pl.DataFrame({"v": _v, "g": _v % 16})',
        "data = _df",
        "return (data,)",
    ])
    # The slider. In marimo a UI value change re-runs *referrers*, not this cell.
    cell("mo", [
        "threshold = mo.ui.slider(0, 100, value=10)",
        "return (threshold,)",
    ])
    # Affected chain: r0 filters by the slider; each successor transforms its
    # predecessor, so the whole chain is downstream of the slider.
    cell("data, pl, threshold", [
        "r0 = data.filter(pl.col('v') > threshold.value)",
        "return (r0,)",
    ])
    prev = "r0"
    for i in range(1, depth):
        cell(f"pl, {prev}", [
            f"r{i} = {prev}.with_columns((pl.col('v') + 1).alias('v'))",
            f"return (r{i},)",
        ])
        prev = f"r{i}"
    # Terminal view — the fragment an update produces.
    cell(prev, [
        f"chart = f'<div id=chart>rows={{{prev}.height}}</div>'",
        "return (chart,)",
    ])
    # Unaffected cells: depend on `data` only, so the slider never schedules them.
    for j in range(unaffected):
        cell("data, pl", [
            f"u{j} = data.group_by('g').agg(pl.col('v').sum())",
            f"return (u{j},)",
        ])

    out.append('if __name__ == "__main__":')
    out.append("    app.run()")
    out.append("")
    return "\n".join(out)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Print a sample benchmark marimo notebook")
    ap.add_argument("--rows", type=int, default=100_000)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--unaffected", type=int, default=4)
    args = ap.parse_args()
    print(notebook_source(rows=args.rows, depth=args.depth, unaffected=args.unaffected))


if __name__ == "__main__":
    main()
