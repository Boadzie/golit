"""Vector Tiles — a large GeoDataFrame streamed as MVT (GIS phase 2.5).

60,000 synthetic points over Greater Accra — far past what `geo_map` could inline as GeoJSON
without choking the browser. `gis.vector_tiles` keeps the data server-side and streams only
the features in each visible tile. A value filter and a color-by select drive it: changing
the filter re-runs the data + map (new tiles); changing only the color column re-renders
just the map. The `stats` view depends on the filtered frame, so it tracks the filter but
not the color change.

    pip install "golit[gis,gis-vector-tiles]"
    golit run examples/vector_tiles/app.py
"""

from __future__ import annotations

import geopandas as gpd
import golit.gis as gis
import golit.ui as ui
import numpy as np
from golit import App, create_app, select, slider

# 60k points clustered in a few hotspots over a Greater-Accra bbox.
_RNG = np.random.default_rng(0)
_N = 60_000
_W, _S, _E, _N_ = -0.40, 5.45, 0.10, 5.80
_CENTERS = [(-0.20, 5.62), (0.00, 5.70), (-0.30, 5.52), (0.05, 5.55)]
_ZONES = ["North", "East", "South", "West"]

_pick = _RNG.integers(0, len(_CENTERS), _N)
_cx = np.array([_CENTERS[i][0] for i in _pick]) + _RNG.normal(0, 0.04, _N)
_cy = np.array([_CENTERS[i][1] for i in _pick]) + _RNG.normal(0, 0.03, _N)
_lon = np.clip(_cx, _W, _E)
_lat = np.clip(_cy, _S, _N_)
_value = np.clip(_RNG.normal(50, 22, _N), 0, 100).round(1)

_POINTS = gpd.GeoDataFrame(
    {"value": _value, "zone": [_ZONES[i] for i in _pick]},
    geometry=gpd.points_from_xy(_lon, _lat),
    crs="EPSG:4326",
)

app = App(title="Vector Tiles")


@app.source
def points() -> gpd.GeoDataFrame:
    return _POINTS


@app.reactive
def visible(points: gpd.GeoDataFrame, min_value: int = slider(0, 90, default=0, step=10,
                                                              label="Min value")):
    return points[points["value"] >= min_value]


@app.view
def map(
    visible: gpd.GeoDataFrame,
    color_by: str = select(["value", "zone"], default="value", label="Color by"),
):
    # 60k points as vector tiles — only the visible tiles stream, on initial load and swaps.
    return gis.vector_tiles(
        visible, color=color_by, tooltip=["value", "zone"], max_zoom=12, height="500px"
    )


@app.view
def stats(visible: gpd.GeoDataFrame) -> str:
    # Depends on the filtered frame — tracks the value filter, ignores the color change.
    return ui.columns(
        [
            ui.metric("Points shown", f"{len(visible):,}"),
            ui.metric("Mean value", f"{visible['value'].mean():.1f}" if len(visible) else "—"),
        ]
    )


application = create_app(app)
