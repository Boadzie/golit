"""Charts Gallery — the same reactive data through four chart libraries.

One slider + region filter feed an aggregation, and Plotly, Altair, Bokeh, and
AnyChart each render it. Move the slider: the dirty subgraph reruns once and all
four chart fragments swap. Golit auto-detects Plotly/Altair/Bokeh *figures*
returned from a view; AnyChart has no Python figure, so ``anychart()`` builds the
mount from the DataFrame.

    pip install "golit[charts]"        # plotly, altair, bokeh (AnyChart = CDN, no pkg)
    golit run examples/charts_gallery/app.py
"""

from __future__ import annotations

import polars as pl
from golit import App, create_app, select, slider
from golit.charts import anychart

app = App(title="Charts Gallery")

SAMPLE = pl.DataFrame(
    {
        "region": ["North", "North", "South", "South", "East", "East", "West", "West"],
        "product": ["A", "B", "A", "B", "A", "B", "A", "B"],
        "revenue": [120, 80, 200, 60, 95, 140, 175, 45],
    }
)
REGIONS = ["All", "North", "South", "East", "West"]
ACCENT = "#1565C0"


@app.source
def data() -> pl.DataFrame:
    return SAMPLE


@app.reactive
def filtered(
    data: pl.DataFrame,
    threshold: int = slider(0, 200, default=50, label="Min revenue"),
    region: str = select(REGIONS, default="All", label="Region"),
) -> pl.DataFrame:
    out = data.filter(pl.col("revenue") > threshold)
    if region != "All":
        out = out.filter(pl.col("region") == region)
    return out


@app.reactive
def by_region(filtered: pl.DataFrame) -> pl.DataFrame:
    return filtered.group_by("region").agg(pl.col("revenue").sum().alias("revenue")).sort("region")


def _missing(lib: str, err: Exception) -> str:
    return (
        '<div class="text-sm text-on-surface-variant">'
        f"Install <code>golit[charts]</code> to see the {lib} view "
        f'<span class="font-mono text-xs">({err})</span>.</div>'
    )


@app.view
def plotly_chart(by_region: pl.DataFrame):
    try:
        import plotly.express as px
    except ImportError as err:
        return _missing("Plotly", err)
    # plotly.express takes the Polars frame directly (narwhals); the returned
    # Figure is auto-detected and rendered as an interactive mount.
    fig = px.bar(by_region, x="region", y="revenue", title="Plotly Express")
    fig.update_traces(marker_color=ACCENT)
    fig.update_layout(margin=dict(l=40, r=20, t=40, b=30), height=320)
    return fig


@app.view
def altair_chart(by_region: pl.DataFrame):
    try:
        import altair as alt
    except ImportError as err:
        return _missing("Altair", err)
    chart = (
        alt.Chart(alt.Data(values=by_region.to_dicts()))
        .mark_bar(color=ACCENT)
        .encode(x=alt.X("region:N", title="Region"), y=alt.Y("revenue:Q", title="Revenue"))
        .properties(title="Altair", width="container", height=280)
    )
    return chart


@app.view
def bokeh_chart(by_region: pl.DataFrame):
    try:
        from bokeh.plotting import figure
    except ImportError as err:
        return _missing("Bokeh", err)
    regions = by_region["region"].to_list()
    revenue = by_region["revenue"].to_list()
    fig = figure(x_range=regions or [""], height=320, title="Bokeh", sizing_mode="stretch_width")
    fig.vbar(x=regions, top=revenue, width=0.8, fill_color=ACCENT, line_color=None)
    fig.y_range.start = 0
    return fig


@app.view
def anychart_chart(by_region: pl.DataFrame):
    return anychart(by_region, "region", "revenue", kind="column", title="AnyChart")


application = create_app(app)
