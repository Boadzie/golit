"""Great Tables — Golit auto-renders a ``great_tables`` ``GT`` object a view returns.

Build a polished display table from a Polars frame (header, formatted currency/percent columns,
a source note) and just return it from an ``@app.view`` — Golit detects the ``GT`` and embeds
its self-contained HTML (styles scoped to the table, no JavaScript). It's reactive like any
view: move the slider and the table redraws.

    pip install "golit[tables]"
    golit run examples/great_tables/app.py
"""

from __future__ import annotations

import golit.ui as ui
import polars as pl
from golit import App, create_app, slider
from great_tables import GT, md

app = App(title="Great Tables")

_DATA = pl.DataFrame(
    {
        "Region": ["North", "South", "East", "West", "Central"],
        "Reps": [12, 9, 15, 7, 11],
        "Revenue": [184_200, 142_900, 221_500, 98_400, 167_300],
        "Growth": [0.082, -0.014, 0.121, 0.043, 0.067],
    }
)


@app.reactive
def filtered(
    min_revenue: int = slider(0, 200_000, default=100_000, step=10_000, label="Min revenue"),
) -> pl.DataFrame:
    return _DATA.filter(pl.col("Revenue") >= min_revenue).sort("Revenue", descending=True)


@app.view
def report(filtered: pl.DataFrame):
    if not filtered.height:
        return ui.alert("No regions above that revenue threshold.", kind="warning")
    return ui.gt_theme(  # style the GT to match golit's shadcn tables
        GT(filtered, rowname_col="Region")
        .tab_header(title="Regional Sales", subtitle="Revenue and YoY growth by region")
        .fmt_currency(columns="Revenue", decimals=0)
        .fmt_percent(columns="Growth", decimals=1)
        .fmt_number(columns="Reps", decimals=0)
        .cols_label(Reps="Sales reps", Growth="YoY growth")
        .tab_source_note(md("Source: _illustrative sample data_."))
    )


application = create_app(app)
