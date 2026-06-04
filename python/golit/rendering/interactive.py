"""Interactive JS charts (Plotly, Altair/Vega-Lite, Bokeh, AnyChart).

Lets-Plot renders to static SVG, which an HTMX swap handles like any other markup.
The libraries here are *client-side*: they ship a JSON spec and a JS runtime draws
it in the browser. To keep that compatible with Golit's fragment transport — POST
out-of-band swaps and SSE pushes, not just the first page load — a view does **not**
return ready-made `<script>` HTML. Instead it returns a library-agnostic *mount*:

    <div class="golit-chart" data-chart-lib="plotly" data-chart-spec="{…json…}"></div>

The page shell (see ``html.py``) registers ``htmx.onLoad`` with a bootstrap that
finds these mounts, lazy-loads the right CDN runtime once, and draws the spec —
on the initial render, on every swap, and on SSE pushes alike. No inline script
to (mis)fire, so the same fragment works on all three paths.

Plotly/Altair/Bokeh figures are auto-detected (``try_interactive``); AnyChart has
no Python figure object, so :func:`anychart` builds a spec from a DataFrame or rows.
"""

from __future__ import annotations

import html as _html
import json
from typing import Any

import polars as pl

# Inline-block mount; charts size themselves once their runtime draws.
_MOUNT_CLASS = (
    "golit-chart bg-surface-container-lowest rounded-xl p-4 shadow-sm overflow-auto min-h-[20rem]"
)


def _mount(lib: str, spec_json: str, *, version: str | None = None) -> str:
    """A library-agnostic chart placeholder for the shell bootstrap to hydrate."""
    ver = f' data-chart-version="{_html.escape(version, quote=True)}"' if version else ""
    spec_attr = _html.escape(spec_json, quote=True)
    return (
        f'<div class="{_MOUNT_CLASS}" data-chart-lib="{lib}"{ver} '
        f'data-chart-spec="{spec_attr}"></div>'
    )


def chart_spec(lib: str, spec: Any, *, version: str | None = None) -> str:
    """Mount a chart from a *raw spec* already in the JS runtime's wire format — a
    plain ``dict`` (or pre-serialized JSON string) — skipping the heavy Python figure
    object.

    Returning a ``plotly.graph_objects.Figure`` (or an Altair chart) is convenient, but
    constructing and ``to_json``-ing it costs hundreds of microseconds and ships
    kilobytes of default template on *every* interaction — a tax a view that rebuilds
    its chart each update pays in full. Handing Golit the spec directly is the same JSON
    the runtime draws, far cheaper to produce and far smaller on the wire::

        @app.view
        def revenue(by_region: pl.DataFrame):
            return chart_spec("plotly", {
                "data": [{"type": "bar", "x": by_region["region"].to_list(),
                          "y": by_region["revenue"].to_list()}],
                "layout": {"margin": {"t": 10}},
            })

    ``lib`` is any runtime the shell bootstrap knows (``plotly``, ``vega``, ``bokeh``,
    ``anychart``); the spec must be in that runtime's own format (e.g. a Plotly
    ``{"data": [...], "layout": {...}}``). ``version`` pins the runtime where it matters
    (Bokeh). For the convenient path, just return the figure object — :func:`try_interactive`
    serializes it; for the hot path, build the spec and use this."""
    spec_json = spec if isinstance(spec, str) else json.dumps(spec)
    return _mount(lib, spec_json, version=version)


def try_interactive(value: Any) -> str | None:
    """Render a Plotly/Altair/Bokeh figure to a mount fragment, else ``None``.

    Detection is by the value's defining module, so the framework never imports
    these libraries itself — only Bokeh's serializer is imported, and only when a
    Bokeh figure actually shows up (so it's necessarily installed)."""
    root = (type(value).__module__ or "").split(".", 1)[0]

    if root == "plotly" and callable(getattr(value, "to_json", None)):
        return _mount("plotly", value.to_json())  # {"data": …, "layout": …}

    if root == "altair" and callable(getattr(value, "to_json", None)):
        return _mount("vega", value.to_json())  # a Vega-Lite spec

    if root == "bokeh":
        import bokeh
        from bokeh.embed import json_item

        # Pin BokehJS to the installed Bokeh so the wire format matches.
        return _mount("bokeh", json.dumps(json_item(value)), version=bokeh.__version__)

    return None


def _anychart_rows(data: Any, x: str | None, y: str | None) -> list[list[Any]]:
    if isinstance(data, pl.DataFrame):
        if x is None or y is None:
            raise ValueError("anychart(df, x, y, …): x and y column names are required")
        labels = data[x].to_list()
        values = data[y].to_list()
        return [[str(a), b] for a, b in zip(labels, values, strict=True)]
    return [list(row) for row in data]


def anychart(
    data: Any,
    x: str | None = None,
    y: str | None = None,
    *,
    kind: str = "column",
    title: str | None = None,
) -> str:
    """Build an AnyChart mount from a Polars ``DataFrame`` (``x``/``y`` columns) or
    a sequence of ``[label, value]`` rows.

        @app.view
        def revenue(by_region: pl.DataFrame):
            return anychart(by_region, "region", "revenue", kind="column", title="Revenue")

    ``kind`` is any AnyChart constructor: ``column``/``bar``/``line``/``area``/
    ``spline``/``pie``/``donut``."""
    spec: dict[str, Any] = {"kind": kind, "data": _anychart_rows(data, x, y)}
    if title is not None:
        spec["title"] = title
    return _mount("anychart", json.dumps(spec))
