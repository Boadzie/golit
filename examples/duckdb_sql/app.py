"""DuckDB SQL — reactive nodes written as SQL over Polars frames.

``golit.sql(query, **frames)`` runs DuckDB in-process over the named upstream
frames and returns Polars, so a SQL node memoizes and renders like any other. The
slider feeds straight into the aggregation's WHERE clause; only the chart and table
re-render when it moves.

    pip install "golit[sql]"
    golit run examples/duckdb_sql/app.py
"""

from __future__ import annotations

import polars as pl
from golit import App, create_app, select, slider, sql
from golit.charts import aes, geom_bar, ggplot, ggsize, labs

app = App(title="DuckDB SQL")

SAMPLE = pl.DataFrame(
    {
        "region": ["North", "North", "South", "South", "East", "East", "West", "West"],
        "product": ["A", "B", "A", "B", "A", "B", "A", "B"],
        "revenue": [120, 80, 200, 60, 95, 140, 175, 45],
    }
)
REGIONS = ["All", "North", "South", "East", "West"]


@app.source
def data() -> pl.DataFrame:
    return SAMPLE


@app.reactive
def by_region(
    data: pl.DataFrame,
    threshold: int = slider(0, 200, default=40, label="Min revenue"),
    region: str = select(REGIONS, default="All", label="Region"),
) -> pl.DataFrame:
    where = f"revenue > {int(threshold)}"
    if region != "All":
        where += f" AND region = '{region}'"
    return sql(
        "SELECT region, sum(revenue)::BIGINT AS revenue "
        f"FROM d WHERE {where} GROUP BY region ORDER BY region",
        d=data,
    )


@app.view
def chart(by_region: pl.DataFrame):
    return (
        ggplot(by_region, aes("region", "revenue"))
        + geom_bar(stat="identity", fill="#1565C0")
        + labs(x="Region", y="Revenue")
        + ggsize(640, 340)
    )


@app.view
def table(by_region: pl.DataFrame) -> pl.DataFrame:
    return by_region


application = create_app(app)
