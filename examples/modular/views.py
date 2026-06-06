"""Views — renderable leaves. Each returns markup Golit swaps into the page by node id.

A view in this module depends on reactives from ``reactives.py`` and the source from
``sources.py`` by name; Golit wires them across modules when it builds the graph.
"""

from __future__ import annotations

import golit.ui as ui
import polars as pl
from _app import app


@app.view
def headline(total_revenue: int, filtered: pl.DataFrame) -> str:
    """KPI row — recomputes only when its inputs change."""
    return ui.grid(
        [
            ui.scorecard("Revenue", f"${total_revenue:,}", icon="payments", kind="primary"),
            ui.scorecard("Rows", str(filtered.height), icon="table_rows"),
        ],
        cols=2,
    )


@app.view
def regions(by_region: pl.DataFrame) -> str:
    """Per-region rollup as a styled table."""
    return ui.card(ui.table(by_region, highlight="revenue"), title="By region")


@app.view
def detail(filtered: pl.DataFrame) -> str:
    """The filtered rows."""
    return ui.card(ui.table(filtered), title="Filtered rows")
