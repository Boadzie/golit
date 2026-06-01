"""Turning a view node's return value into UI markup.

The transport is HTML fragments, so a view may return anything Golit knows how to
serialize to markup. Resolution order (first match wins):

1. an object implementing ``__golit_render__() -> str`` (the :class:`Renderer` protocol);
2. a ``str`` (treated as trusted, developer-authored markup) or ``bytes``;
3. a Lets-Plot spec → static SVG;
4. anything exposing ``to_svg()`` (other static-SVG sources);
5. a Polars ``DataFrame`` → an HTML table;
6. anything exposing ``_repr_html_()`` (pandas, Plotly static, …);
7. a Matplotlib figure → SVG;
8. fallback: escaped ``repr`` in a ``<pre>``.
"""

from __future__ import annotations

import html
import io
from typing import Any, Protocol, runtime_checkable

import polars as pl

from .charts import is_plot, plot_to_svg


@runtime_checkable
class Renderer(Protocol):
    """Objects that know how to render themselves to a markup fragment."""

    def __golit_render__(self) -> str: ...


def _wrap_svg(svg: str) -> str:
    return f'<div class="golit-chart">{svg}</div>'


def _to_text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else str(value)


def _dataframe_table(df: pl.DataFrame, *, max_rows: int = 50) -> str:
    head = df.head(max_rows)
    cols = "".join(f"<th>{html.escape(str(c))}</th>" for c in head.columns)
    rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in row) + "</tr>"
        for row in head.iter_rows()
    )
    more = (
        f'<caption class="golit-table-more">showing {max_rows} of {df.height} rows</caption>'
        if df.height > max_rows
        else ""
    )
    return (
        f'<table class="golit-table">{more}'
        f"<thead><tr>{cols}</tr></thead><tbody>{rows}</tbody></table>"
    )


def _is_mpl_figure(value: Any) -> bool:
    module = type(value).__module__ or ""
    return module.startswith("matplotlib") and callable(getattr(value, "savefig", None))


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
    to_svg = getattr(value, "to_svg", None)
    if callable(to_svg):
        return _wrap_svg(_to_text(to_svg()))
    if isinstance(value, pl.DataFrame):
        return _dataframe_table(value)
    repr_html = getattr(value, "_repr_html_", None)
    if callable(repr_html):
        return _to_text(repr_html())
    if _is_mpl_figure(value):
        return _mpl_svg(value)
    return f'<pre class="golit-value">{html.escape(str(value))}</pre>'
