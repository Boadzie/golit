# Charts

Golit ships charting that fits its fragment transport: charts are just markup an HTMX swap handles like any other. You get two flavors — **static SVG** (the default, zero client runtime) and **interactive** client-side charts (opt-in).

## Lets-Plot → static SVG (default)

[Lets-Plot](https://lets-plot.org/) is a grammar-of-graphics library — a faithful port of R's ggplot2. Golit runs it in static, no-JavaScript mode and renders to **bare SVG server-side**. No charting runtime ships to the browser; the SVG *is* the fragment.

Import the grammar from `golit.charts` and return a plot spec from a view:

```python
from golit.charts import aes, geom_bar, ggplot, ggsize, labs


@app.view
def chart(by_region: pl.DataFrame):
    return (
        ggplot(by_region, aes("region", "revenue"))
        + geom_bar(stat="identity", fill="#1565C0")
        + labs(x="Region", y="Revenue")
        + ggsize(640, 340)
    )
```

`golit.charts` re-exports the full Lets-Plot grammar (`ggplot`, `aes`, every `geom_*`, `ggsize`, `labs`, scales, themes, …). View nodes consume Polars frames directly and return specs; Golit compiles a spec to SVG only when the view is dirty.

!!! tip "This is the decisive fit"
    Because the chart is static SVG, it travels on *every* path identically — initial load, POST swap, and SSE push — with no per-chart JS bundle and no hydration. It's why static charting is the default.

## Interactive charts (Plotly / Altair / Bokeh)

When you want pan/zoom/hover, return a **Plotly, Altair, or Bokeh figure**. Golit auto-detects the figure type and renders a client-side chart that hydrates on the initial load *and* across POST/SSE swaps.

Install the extra:

```bash
pip install "golit[charts]"
```

=== "Plotly"

    ```python
    @app.view
    def chart(by_region: pl.DataFrame):
        import plotly.express as px
        # plotly.express takes the Polars frame directly (via narwhals).
        fig = px.bar(by_region, x="region", y="revenue", title="Revenue")
        return fig
    ```

=== "Altair"

    ```python
    @app.view
    def chart(by_region: pl.DataFrame):
        import altair as alt
        return (
            alt.Chart(alt.Data(values=by_region.to_dicts()))
            .mark_bar()
            .encode(x="region:N", y="revenue:Q")
            .properties(width="container", height=280)
        )
    ```

=== "Bokeh"

    ```python
    @app.view
    def chart(by_region: pl.DataFrame):
        from bokeh.plotting import figure
        regions = by_region["region"].to_list()
        fig = figure(x_range=regions or [""], height=320, sizing_mode="stretch_width")
        fig.vbar(x=regions, top=by_region["revenue"].to_list(), width=0.8)
        return fig
    ```

### How it works

A view does **not** return ready-made `<script>` HTML. Instead Golit emits a library-agnostic *mount*:

```html
<div class="golit-chart" data-chart-lib="plotly" data-chart-spec="{…json…}"></div>
```

The page shell registers an `htmx.onLoad` bootstrap that finds these mounts, lazy-loads the right CDN runtime **once**, and draws the spec — on the initial render, on every swap, and on SSE pushes alike. There's no inline script to misfire, so the same fragment works on all three paths. (Bokeh is special: its JS must match the installed Python Bokeh, so the version rides on the mount and the loader builds the URLs from it.)

## AnyChart

AnyChart has no Python figure object, so Golit gives you a helper that builds a mount from a DataFrame (or `[label, value]` rows). It loads from a CDN — no Python package, no extra to install:

```python
from golit.charts import anychart


@app.view
def revenue(by_region: pl.DataFrame):
    return anychart(by_region, "region", "revenue", kind="column", title="Revenue")
```

`kind` is any AnyChart constructor: `column`, `bar`, `line`, `area`, `spline`, `pie`, `donut`, `funnel`.

## Bring your own

The chart support isn't a cage. **Anything that exports static SVG/PNG/HTML server-side** drops straight into the fragment model: a Matplotlib figure (rendered via `savefig`), a pandas object with `_repr_html_`, or a raw SVG string all render. See the full [resolution order](views.md#what-a-view-can-return). The only path that needs the opt-in interactive escape hatch is a chart that *requires* a client-side JS runtime — which is exactly what the Plotly/Altair/Bokeh detection handles.

## Full example

The [`charts_gallery`](https://github.com/boadzie/golit/tree/main/examples/charts_gallery) example renders the *same* reactive aggregation through all four libraries at once — move the slider and every chart fragment swaps from one recompute.

## Next

**[UI components](ui-components.md)** — cards, metrics, tabs, alerts, and more, all server-rendered.
