"""Turning a view node's return value into UI markup.

The transport is HTML fragments, so a view may return anything Golit knows how to
serialize to markup. Resolution order (first match wins):

1. an object implementing ``__golit_render__() -> str`` (the :class:`Renderer` protocol);
2. a ``str`` (treated as trusted, developer-authored markup) or ``bytes``;
3. a Lets-Plot spec → static SVG;
4. a Plotly/Altair/Bokeh figure → an interactive client-side chart mount;
5. anything exposing ``to_svg()`` (other static-SVG sources);
6. a Polars ``DataFrame`` → an HTML table;
7. a GeoPandas ``GeoDataFrame`` → a native MapLibre map (``golit.gis.geo_map``);
8. anything exposing ``_repr_html_()`` (pandas, …);
9. a Matplotlib figure → SVG;
10. fallback: escaped ``repr`` in a ``<pre>``.
"""

from __future__ import annotations

import html
import io
from typing import Any, Protocol, runtime_checkable

import polars as pl

from ..data import is_duckdb_relation, relation_to_polars
from .charts import is_plot, plot_to_svg
from .interactive import try_interactive


@runtime_checkable
class Renderer(Protocol):
    """Objects that know how to render themselves to a markup fragment."""

    def __golit_render__(self) -> str: ...


def _wrap_svg(svg: str) -> str:
    return (
        '<div class="golit-chart bg-surface-container-lowest rounded-xl p-4 '
        f'shadow-sm overflow-auto">{svg}</div>'
    )


def _to_text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else str(value)


def _dataframe_table(df: pl.DataFrame, *, max_rows: int = 50) -> str:
    head = df.head(max_rows)
    cols = "".join(
        f'<th class="px-4 py-3 text-left">{html.escape(str(c))}</th>' for c in head.columns
    )
    td = '<td class="px-4 py-2.5 font-mono text-xs">{}</td>'
    rows = "".join(
        '<tr class="hover:bg-surface-container transition-all">'
        + "".join(td.format(html.escape(str(v))) for v in row)
        + "</tr>"
        for row in head.iter_rows()
    )
    more = (
        f'<p class="text-[10px] text-on-surface-variant text-right pt-2 font-mono uppercase '
        f'tracking-widest">showing {max_rows} of {df.height} rows</p>'
        if df.height > max_rows
        else ""
    )
    return (
        '<div class="overflow-x-auto"><table class="golit-table w-full text-left border-collapse">'
        '<thead><tr class="bg-surface-container-high/50 font-mono text-[10px] uppercase '
        f'tracking-widest text-outline">{cols}</tr></thead>'
        f'<tbody class="divide-y divide-outline-variant/10 text-sm">{rows}</tbody>'
        f"</table>{more}</div>"
    )


def _is_mpl_figure(value: Any) -> bool:
    module = type(value).__module__ or ""
    return module.startswith("matplotlib") and callable(getattr(value, "savefig", None))


def _is_geodataframe(value: Any) -> bool:
    cls = type(value)
    return cls.__name__ == "GeoDataFrame" and (cls.__module__ or "").startswith("geopandas")


def _mpl_svg(fig: Any) -> str:
    buffer = io.StringIO()
    fig.savefig(buffer, format="svg")
    return _wrap_svg(buffer.getvalue())


def render_value(value: Any) -> str:
    """Render a view node's return value to an HTML fragment body."""
    if value is None:
        return ""
    if isinstance(value, Renderer):
        return value.__golit_render__()
    if isinstance(value, str):
        return value  # trusted markup
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    if is_plot(value):
        return _wrap_svg(plot_to_svg(value))
    interactive = try_interactive(value)  # Plotly / Altair / Bokeh figures
    if interactive is not None:
        return interactive
    to_svg = getattr(value, "to_svg", None)
    if callable(to_svg):
        return _wrap_svg(_to_text(to_svg()))
    if isinstance(value, pl.DataFrame):
        return _dataframe_table(value)
    if is_duckdb_relation(value):
        return _dataframe_table(relation_to_polars(value))
    if _is_geodataframe(value):
        # A GeoDataFrame also has _repr_html_ (a table) — route it to a map first.
        from ..gis import geo_map

        return geo_map(value)
    repr_html = getattr(value, "_repr_html_", None)
    if callable(repr_html):
        return _to_text(repr_html())
    if _is_mpl_figure(value):
        return _mpl_svg(value)
    return (
        '<pre class="golit-value font-mono text-xs bg-surface-container-highest '
        f'rounded-lg p-3 text-on-surface">{html.escape(str(value))}</pre>'
    )
