"""Synthetic Golit apps with a controllable graph shape.

The B1 hero chart needs apps where three knobs vary independently:

* ``rows``        — dataset size (drives per-node *compute* cost).
* ``depth``       — length of the **affected chain** the slider feeds
                    (the methodology's downstream-depth {1, 3, 10}).
* ``unaffected``  — number of nodes that depend only on ``data`` and so are
                    **never** in the slider's dirty subgraph. This is the x-axis:
                    grow it and a reactive engine's update cost must stay flat.

Shape::

    data ─┬─> r0(threshold) ─> r1 ─> … ─> r{depth-1} ─> chart   (affected chain)
          ├─> u0   ┐
          ├─> u1   │  unaffected nodes — recomputed on full render,
          └─> …    ┘  but the slider never touches them

``data`` has no inputs, so moving the slider leaves it (and every ``u*``) clean;
only the affected chain re-executes. Dependencies are inferred from parameter
names, exactly as in a hand-written app — these functions just have their
signatures synthesized.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import numpy as np
import polars as pl
from golit import App, slider

from .instrument import timed_body

_EMPTY = inspect.Parameter.empty


def _make_frame(rows: int, *, groups: int = 16, seed: int = 0) -> pl.DataFrame:
    """A two-column frame: ``v`` (the filtered/aggregated metric) and ``g`` (a
    low-cardinality group key for the unaffected aggregations)."""
    rng = np.random.default_rng(seed)
    v = rng.integers(0, 100, size=rows)
    return pl.DataFrame({"v": v, "g": v % groups})


def _node(
    node_id: str,
    params: list[tuple[str, Any]],
    body: Callable[[dict[str, Any]], Any],
) -> Callable[..., Any]:
    """Build a node function with a synthesized signature.

    ``params`` is ``[(name, default)]`` where ``default`` is a widget instance for
    an input edge or :data:`_EMPTY` for a dependency edge — the same two cases
    :func:`golit.nodes.inspect_params` distinguishes. The body is timed via
    :func:`bench.instrument.timed_body`.
    """
    timed = timed_body(body)

    def fn(**kwargs: Any) -> Any:
        return timed(kwargs)

    fn.__name__ = node_id
    sig_params = [
        inspect.Parameter(n, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=d) for n, d in params
    ]
    fn.__signature__ = inspect.Signature(sig_params)  # type: ignore[attr-defined]
    return fn


def _chart_body(kind: str, prev: str) -> Callable[[dict[str, Any]], Any]:
    """The terminal view's body. ``text`` is the wire-minimal synthetic fragment used
    by B1/B2 (isolates the engine); ``svg``/``plotly`` render a *real* chart of the
    affected frame's per-group sums — the same 16-bar chart the Dash twin draws — so a
    real-transport comparison renders like-for-like. ``svg`` returns a Lets-Plot chart
    (Golit renders it to a static SVG, no client runtime); ``plotly`` returns a Plotly
    figure (Golit ships it as a spec mount, like Dash)."""
    if kind == "text":
        return lambda kw, _p=prev: f'<div id="chart">rows={kw[_p].height}</div>'
    if kind == "svg":
        def svg_body(kw: dict[str, Any], _p: str = prev) -> Any:
            from golit.charts import aes, geom_bar, ggplot

            agg = kw[_p].group_by("g").agg(pl.col("v").sum()).sort("g")
            data = {"g": agg["g"].to_list(), "v": agg["v"].to_list()}
            return ggplot(data, aes("g", "v")) + geom_bar(stat="identity")
        return svg_body
    if kind == "plotly":
        def plotly_body(kw: dict[str, Any], _p: str = prev) -> Any:
            import plotly.graph_objects as go

            agg = kw[_p].group_by("g").agg(pl.col("v").sum()).sort("g")
            return go.Figure(go.Bar(x=agg["g"].to_list(), y=agg["v"].to_list()))
        return plotly_body
    if kind == "spec":
        def spec_body(kw: dict[str, Any], _p: str = prev) -> Any:
            from golit.rendering import chart_spec

            # The *same* 16-bar chart as ``plotly``/``svg``, but handed over as the raw
            # wire spec the runtime draws — skipping the graph_objects build and Plotly's
            # to_json (the hot path a view that rebuilds its chart each update should use).
            agg = kw[_p].group_by("g").agg(pl.col("v").sum()).sort("g")
            return chart_spec("plotly", {
                "data": [{"type": "bar", "x": agg["g"].to_list(), "y": agg["v"].to_list()}],
                "layout": {"margin": {"t": 10}},
            })
        return spec_body
    raise ValueError(f"unknown chart kind: {kind!r}")


def make_app(*, rows: int, depth: int, unaffected: int, chart: str = "text") -> App:
    """Build a synthetic app with the given shape (see module docstring).

    ``chart`` selects the terminal view: ``text`` (default, wire-minimal — the B1/B2
    engine isolation), ``svg`` (a real Lets-Plot chart Golit renders server-side),
    ``plotly`` (a real Plotly figure Golit ships as a spec, matching idiomatic Dash), or
    ``spec`` (the same chart handed over as a raw dict via ``chart_spec`` — the hot
    path that skips the figure build + ``to_json``)."""
    if depth < 1:
        raise ValueError("depth must be >= 1")
    frame = _make_frame(rows)
    app = App(title=f"bench r{rows} d{depth} u{unaffected}")

    # Source with no inputs: the slider can never dirty it, so it stays warm.
    app.source(_node("data", [], lambda kw, _f=frame: _f))

    # Affected chain: r0 filters by the slider; each subsequent node transforms
    # its predecessor, so a committed slider change cascades the whole chain.
    sl = slider(0, 100, default=10, label="threshold")
    app.reactive(
        _node(
            "r0",
            [("data", _EMPTY), ("threshold", sl)],
            lambda kw: kw["data"].filter(pl.col("v") > kw["threshold"]),
        )
    )
    prev = "r0"
    for i in range(1, depth):
        app.reactive(
            _node(
                f"r{i}",
                [(prev, _EMPTY)],
                lambda kw, _p=prev: kw[_p].with_columns((pl.col("v") + 1).alias("v")),
            )
        )
        prev = f"r{i}"

    # Terminal view — the fragment an update returns (text / svg / plotly).
    app.view(_node("chart", [(prev, _EMPTY)], _chart_body(chart, prev)))

    # Unaffected nodes: depend on `data` only, so the slider never schedules them.
    # Each does a bounded aggregation, so a *full* recompute climbs with `unaffected`.
    for j in range(unaffected):
        app.reactive(
            _node(
                f"u{j}",
                [("data", _EMPTY)],
                lambda kw: kw["data"].group_by("g").agg(pl.col("v").sum()),
            )
        )

    app.build()
    return app


def memo_heavy(frame: pl.DataFrame) -> pl.DataFrame:
    """The shared, expensive upstream of the memoization benches: a full-frame sort +
    derive — the kind of step a real app computes once and feeds to several views. Cost
    scales with rows. Both engines run the *same* function, so the only difference the
    bench measures is whether it is recomputed (Dash) or memoized (Golit)."""
    return frame.sort("v").with_columns((pl.col("v") * 2).alias("w"))


def memo_payload(heavy: pl.DataFrame, threshold: int) -> dict[str, Any]:
    """The cheap per-view work, identical on both engines: filter the shared frame by the
    slider and aggregate to the 16-bar Plotly bar spec (a raw dict, no figure object)."""
    agg = heavy.filter(pl.col("v") > threshold).group_by("g").agg(pl.col("v").sum()).sort("g")
    return {"data": [{"type": "bar", "x": agg["g"].to_list(), "y": agg["v"].to_list()}],
            "layout": {"margin": {"t": 10}}}


def make_memo_app(*, rows: int, on_heavy: Callable[[], None] | None = None) -> App:
    """Shared-upstream app for the memoization bench::

        data ── heavy(data) ──┬── view_a(heavy, threshold_a)
                              └── view_b(heavy, threshold_b)

    Moving ``threshold_a`` dirties only ``view_a``; ``heavy`` depends solely on ``data``
    so it stays clean and the kernel memoizes it (executed zero times per update). ``on_heavy``
    (if given) is invoked each time ``heavy`` runs — the in-process bench uses it to prove
    that. Views hand the chart back as a raw dict via ``chart_spec``."""
    from golit.rendering import chart_spec

    frame = _make_frame(rows)
    app = App(title=f"memo r{rows}")

    def data() -> pl.DataFrame:
        return frame

    def heavy(data: pl.DataFrame) -> pl.DataFrame:
        if on_heavy is not None:
            on_heavy()
        return memo_heavy(data)

    def view_a(
        heavy: pl.DataFrame, threshold_a: Any = slider(0, 100, default=10, label="A"),
    ) -> str:
        return chart_spec("plotly", memo_payload(heavy, threshold_a))

    def view_b(
        heavy: pl.DataFrame, threshold_b: Any = slider(0, 100, default=10, label="B"),
    ) -> str:
        return chart_spec("plotly", memo_payload(heavy, threshold_b))

    app.source(data)
    app.reactive(heavy)
    app.view(view_a)
    app.view(view_b)
    app.build()
    return app
