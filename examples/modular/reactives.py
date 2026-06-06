"""Reactives — pure transforms over upstream nodes and inputs.

Each re-runs only when something it depends on changes. Dependencies are inferred from the
parameter names: ``sales`` is the source node above; ``min_revenue`` defaults to a widget, so
it's an input. A node defined in *this* module can depend on one defined in *another* — the
graph is resolved across the whole shared ``app``, not per file.
"""

from __future__ import annotations

import polars as pl
from _app import app
from golit import slider


@app.reactive
def filtered(
    sales: pl.DataFrame, min_revenue: int = slider(0, 250, default=80, step=10)
) -> pl.DataFrame:
    """Rows at or above the revenue threshold — re-runs on the slider or new ``sales``."""
    return sales.filter(pl.col("revenue") >= min_revenue)


@app.reactive
def by_region(filtered: pl.DataFrame) -> pl.DataFrame:
    """Revenue and units summed per region."""
    return (
        filtered.group_by("region")
        .agg(pl.col("revenue").sum(), pl.col("units").sum())
        .sort("revenue", descending=True)
    )


@app.reactive
def total_revenue(filtered: pl.DataFrame) -> int:
    """A scalar KPI — memoizes like any other node."""
    return int(filtered["revenue"].sum())
