"""Components Gallery — the new input widgets + golit.ui components, reactively.

A small sales dashboard: a slider and a region multiselect drive a filtered frame;
KPIs (metric), a status callout (alert/badge), a tabbed detail (tabs/table/markdown),
and a progress bar all recompute from it. A switch toggles the table density and a
button demonstrates "on click" reactivity — clicking it re-runs only its own view.

    golit run examples/components_gallery/app.py
"""

from __future__ import annotations

import golit.ui as ui
import polars as pl
from golit import App, button, create_app, multiselect, slider, switch

app = App(title="Components Gallery")

SAMPLE = pl.DataFrame(
    {
        "region": ["North", "North", "South", "South", "East", "East", "West", "West"],
        "product": ["A", "B", "A", "B", "A", "B", "A", "B"],
        "revenue": [120, 80, 200, 60, 95, 140, 175, 45],
    }
)
REGIONS = ["North", "South", "East", "West"]
TOTAL = int(SAMPLE["revenue"].sum())


@app.source
def data() -> pl.DataFrame:
    return SAMPLE


@app.reactive
def filtered(
    data: pl.DataFrame,
    threshold: int = slider(0, 200, default=40, label="Min revenue"),
    regions: list = multiselect(REGIONS, default=REGIONS, label="Regions"),
) -> pl.DataFrame:
    out = data.filter(pl.col("revenue") > threshold)
    if regions:
        out = out.filter(pl.col("region").is_in(regions))
    return out


@app.view
def kpis(filtered: pl.DataFrame) -> str:
    total = int(filtered["revenue"].sum()) if filtered.height else 0
    share = f"+{round(total / TOTAL * 100)}%" if total else "0%"
    return ui.columns(
        [
            ui.metric("Filtered revenue", f"${total:,}", delta=share, help="share of all revenue"),
            ui.metric("Rows", str(filtered.height)),
            ui.metric("Regions", str(filtered["region"].n_unique() if filtered.height else 0)),
        ]
    )


@app.view
def status(filtered: pl.DataFrame) -> str:
    if not filtered.height:
        return ui.alert("No rows match the current filter.", kind="warning", title="Empty")
    return ui.alert(
        ui.badge(f"{filtered.height} rows", kind="primary") + " match the filter.",
        kind="success",
        title="Live",
    )


@app.view
def usage(filtered: pl.DataFrame) -> str:
    return ui.progress(filtered["revenue"].sum() if filtered.height else 0, total=TOTAL,
                       label="Revenue captured")


@app.view
def detail(filtered: pl.DataFrame, compact: bool = switch("Compact", default=False)) -> str:
    shown = filtered.select("region", "revenue") if compact else filtered
    summary = ui.markdown(
        f"### Summary\n\n"
        f"- **{filtered.height}** rows after filtering\n"
        f"- top region by revenue: `{_top_region(filtered)}`\n"
    )
    return ui.card(
        ui.tabs({"Table": ui.table(shown, highlight="revenue"), "Summary": summary}),
        title="Detail",
    )


@app.view
def activity(go: int = button("Refresh")) -> str:
    # `go` changes on every click → this view (and only this one) re-runs.
    clicks = 0 if not go else 1
    return ui.card(
        ui.caption("Click count is illustrative; each click re-runs only this fragment."),
        title="Activity",
        footer=ui.badge("refreshed" if clicks else "idle", kind="secondary"),
    )


def _top_region(df: pl.DataFrame) -> str:
    if not df.height:
        return "—"
    agg = df.group_by("region").agg(pl.col("revenue").sum()).sort("revenue", descending=True)
    return str(agg["region"][0])


application = create_app(app)
