"""Sales Explorer — the canonical Golit demo.

Upload a CSV (or use the built-in sample), then a slider + region filter feed an
aggregation, a Lets-Plot bar chart, a KPI, and a table. The ``overview`` view
depends only on ``data`` — so moving the slider updates the chart/KPI/table but
never re-renders it. That selective recompute is the whole point.

    golit run examples/sales_explorer/app.py
"""

from __future__ import annotations

import polars as pl
from golit import App, create_app, select, slider, upload
from golit.charts import aes, geom_bar, ggplot, ggsize, labs

app = App(title="Sales Explorer")

SAMPLE = pl.DataFrame(
    {
        "region": ["North", "North", "South", "South", "East", "East", "West", "West"],
        "product": ["A", "B", "A", "B", "A", "B", "A", "B"],
        "revenue": [120, 80, 200, 60, 95, 140, 175, 45],
    }
)

REGIONS = ["All", "North", "South", "East", "West"]


@app.source
def data(file=upload("Upload sales CSV", accept=".csv")) -> pl.DataFrame:
    return SAMPLE if file is None else pl.read_csv(file)


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


@app.view
def chart(by_region: pl.DataFrame):
    return (
        ggplot(by_region, aes("region", "revenue"))
        + geom_bar(stat="identity", fill="#1565C0")
        + labs(x="Region", y="Revenue")
        + ggsize(640, 340)
    )


@app.view
def kpi(filtered: pl.DataFrame) -> str:
    total = int(filtered["revenue"].sum()) if filtered.height else 0
    return (
        '<div class="flex items-center justify-between">'
        '<div><p class="text-xs font-bold uppercase tracking-widest text-primary">'
        "Filtered revenue</p>"
        f'<h3 class="font-headline text-4xl font-bold tracking-tight">${total:,}</h3></div>'
        '<span class="font-mono text-sm text-on-surface-variant">'
        f"{filtered.height} rows</span></div>"
    )


@app.view
def table(filtered: pl.DataFrame) -> pl.DataFrame:
    return filtered


@app.view
def overview(data: pl.DataFrame) -> str:
    # Depends only on `data` — unaffected by the slider/region inputs.
    return (
        '<div class="flex gap-10">'
        '<div><p class="text-xs uppercase tracking-widest text-on-surface-variant">Dataset</p>'
        f'<p class="font-mono text-lg">{data.height} rows · '
        f'{data["region"].n_unique()} regions</p></div>'
        '<div><p class="text-xs uppercase tracking-widest text-on-surface-variant">'
        "Total revenue</p>"
        f'<p class="font-mono text-lg">${int(data["revenue"].sum()):,}</p></div></div>'
    )


application = create_app(app)
