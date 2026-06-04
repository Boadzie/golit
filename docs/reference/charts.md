# Charts

## Lets-Plot grammar

`golit.charts` re-exports the full Lets-Plot grammar of graphics — `ggplot`, `aes`, every `geom_*`, `ggsize`, `labs`, scales, and themes. Return a plot spec from a view and Golit renders it to static SVG. See the [Lets-Plot reference](https://lets-plot.org/python/pages/api.html) for the grammar itself, and the [Charts tutorial](../tutorial/charts.md) for usage.

Plotly, Altair, and Bokeh figures need no helper — return one from a view and Golit auto-detects and renders it as an interactive client-side chart.

## chart_spec

The hot path for an interactive view that rebuilds its chart every interaction: hand
Golit the raw wire-format spec (a plain `dict`) instead of a figure object, skipping the
`graph_objects` build and `to_json`. See the [Charts tutorial](../tutorial/charts.md#the-hot-path-chart_spec).

::: golit.rendering.interactive.chart_spec

## anychart

For AnyChart (which has no Python figure object), build a mount explicitly:

::: golit.rendering.interactive.anychart

## try_interactive

The detector used internally to turn a Plotly/Altair/Bokeh figure into a chart mount. Returns the mount HTML, or `None` if the value isn't a recognized figure.

::: golit.rendering.interactive.try_interactive
