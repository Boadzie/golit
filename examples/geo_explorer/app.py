"""Geo Explorer — a reactive map is a view like any other.

A bundled GeoJSON of district polygons; a zone filter and a population slider feed a
GeoPandas filter, and a native MapLibre choropleth renders the result. Moving a control
re-runs *only* the filter + map (and the KPI) — the ``overview`` view depends on the raw
data, so it never re-renders. That selective recompute is the whole point, maps included.

    pip install "golit[gis]"
    golit run examples/geo_explorer/app.py
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import golit.gis as gis
import golit.ui as ui
from golit import App, create_app, select, slider

app = App(title="Geo Explorer")

DATA = Path(__file__).parent / "districts.geojson"
ZONES = ["All", "West", "Central", "East"]


@app.source
def districts() -> gpd.GeoDataFrame:
    return gpd.read_file(DATA)


@app.reactive
def filtered(
    districts: gpd.GeoDataFrame,
    zone: str = select(ZONES, default="All", label="Zone"),
    min_pop: int = slider(0, 40_000, default=15_000, step=1_000, label="Min population"),
) -> gpd.GeoDataFrame:
    out = districts[districts["population"] >= min_pop]
    if zone != "All":
        out = out[out["zone"] == zone]
    return out


@app.view
def map(filtered: gpd.GeoDataFrame):
    # A native MapLibre choropleth — re-rendered only when `filtered` changes.
    if filtered.empty:
        return ui.alert("No districts match the filter.", kind="warning")
    return gis.geo_map(
        filtered,
        color="population",
        tooltip=["name", "zone", "population", "revenue"],
        basemap="positron",  # free OpenFreeMap vector style (the default)
        height="460px",
    )


@app.view
def kpi(filtered: gpd.GeoDataFrame) -> str:
    n = len(filtered)
    pop = int(filtered["population"].sum()) if n else 0
    rev = int(filtered["revenue"].sum()) if n else 0
    return ui.columns(
        [
            ui.metric("Districts", n),
            ui.metric("Population", f"{pop:,}"),
            ui.metric("Revenue", f"${rev:,}"),
        ]
    )


@app.view
def overview(districts: gpd.GeoDataFrame) -> str:
    # Depends only on `districts` — untouched when the filter controls move.
    total = int(districts["population"].sum())
    return ui.card(
        ui.caption(
            f"{len(districts)} districts · {districts['zone'].nunique()} zones · "
            f"{total:,} people. Filter on the left rebuilds only the map + KPIs."
        ),
        title="Dataset",
    )


application = create_app(app)
