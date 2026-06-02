"""Synthetic Dash app — the behavioral twin of ``bench.gen_app.make_app``.

Dash is the rival people *expect* to be a "rerun-everything" framework, but its
docs are explicit: a callback fires only when one of its declared ``Input`` values
changes, and only that callback runs — the layout/data are not re-evaluated. So
Dash is a **manually-wired reactive DAG**, much closer to Golit than to Streamlit.
The faithful translation of our synthetic app makes that concrete:

    data ─┬─> [callback: r0(threshold) ─> … ─> r{depth-1}] ─> chart   (one callback)
          ├─> u0  ┐
          └─> …   ┘  unaffected: depend only on `data` → STATIC layout, no callback

The affected chain is the slider's callback. The ``unaffected`` nodes depend only
on the (static) data, so in idiomatic Dash they are *not* callbacks at all — they
are computed once and placed in the layout, and a slider move never touches them.
Hence Dash, written the way the dataflow actually is, is **flat** in unaffected
count: exactly **one** callback fires per move, regardless of how many unaffected
nodes exist. It is not the rerun-everything rival.

Where Dash genuinely differs from Golit is the **wire**: its callback returns a
Plotly *figure*, which Dash serializes to JSON and ships on every interaction
(plus it needs the plotly.js client runtime to draw it). Golit renders the chart
to a compact static SVG server-side and ships zero client charting code. That is
the comparison this twin sets up — see :mod:`bench.run_b1_dash`.

This module exposes :class:`DashTwin`, a real ``dash.Dash`` app plus two
measurement seams: :meth:`DashTwin.chain` (the server-compute floor — the affected
chain only, the same "server compute, no transport" axis as the other rivals) and
:meth:`DashTwin.figure` (the real per-update payload the callback returns).
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import polars as pl
from dash import Dash, Input, Output, dcc, html


def _frame(rows: int, *, groups: int = 16, seed: int = 0) -> pl.DataFrame:
    """Same two-column frame as the Golit/Streamlit/Marimo twins."""
    rng = np.random.default_rng(seed)
    v = rng.integers(0, 100, size=rows)
    return pl.DataFrame({"v": v, "g": v % groups})


def _affected(data: pl.DataFrame, threshold: int, depth: int) -> pl.DataFrame:
    """The slider-driven chain: filter, then ``depth-1`` transforms — identical to
    the affected chain in every other twin, so the compute floor is comparable."""
    out = data.filter(pl.col("v") > threshold)
    for _ in range(depth - 1):
        out = out.with_columns((pl.col("v") + 1).alias("v"))
    return out


def figure_of(frame: pl.DataFrame) -> go.Figure:
    """The representative chart: a bar of the per-group sums of the affected frame.
    A real visualization (not a text fragment), and the same picture we render as a
    Golit SVG for the bytes-on-the-wire comparison."""
    agg = frame.group_by("g").agg(pl.col("v").sum()).sort("g")
    return go.Figure(go.Bar(x=agg["g"].to_list(), y=agg["v"].to_list()))


class DashTwin:
    """An idiomatic Dash app for one graph shape, with measurement seams.

    The app is real: ``self.app`` has the layout and the registered slider→chart
    callback a Dash dev would write. ``chain`` and ``figure`` expose the two halves
    the benchmark times separately (server compute vs the wire payload).
    """

    def __init__(self, *, rows: int, depth: int, unaffected: int) -> None:
        if depth < 1:
            raise ValueError("depth must be >= 1")
        self.data = _frame(rows)
        self.depth = depth
        self.app = Dash(__name__)

        # Unaffected nodes depend only on the static data, so in Dash they are
        # static layout — computed once, never re-run by a slider move.
        unaffected_divs = [
            html.Div(
                f"u{j}: {int(self.data.group_by('g').agg(pl.col('v').sum())['v'].sum())}",
                id=f"u{j}",
            )
            for j in range(unaffected)
        ]
        self.app.layout = html.Div(
            [
                dcc.Slider(0, 100, value=10, id="threshold"),
                dcc.Graph(id="chart"),
                *unaffected_divs,
            ]
        )

        @self.app.callback(Output("chart", "figure"), Input("threshold", "value"))
        def update_chart(threshold: int) -> go.Figure:
            return figure_of(_affected(self.data, threshold, self.depth))

        # @app.callback returns the function unchanged, so we can drive it directly —
        # the documented way to unit-test a Dash callback without a browser.
        self._update_chart = update_chart

    def chain(self, threshold: int) -> int:
        """Server-compute floor: run the affected chain, return its row count.

        Excludes figure construction and JSON serialization (Dash's transport),
        matching the axis the other rivals are measured on — server compute only.
        """
        return _affected(self.data, threshold, self.depth).height

    def figure(self, threshold: int) -> go.Figure:
        """The real callback: the Plotly figure Dash serializes and ships per move."""
        return self._update_chart(threshold)


def figure_bytes(fig: go.Figure) -> int:
    """Bytes Dash puts on the wire for a figure: its JSON, UTF-8 encoded.

    This is the dominant term of Dash's ``/_dash-update-component`` response (Dash
    wraps it in a thin ``{"response": {"chart": {"figure": …}}}`` envelope)."""
    return len(fig.to_json().encode("utf-8"))
