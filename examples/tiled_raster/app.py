"""Tiled Raster Explorer — stream a large COG as on-demand map tiles (GIS phase 2.5).

A synthetic 2000×2000 "elevation" Cloud-Optimized GeoTIFF (internal 256-px tiles +
overviews) over a Greater-Accra bbox, generated once into the temp dir. `gis.tiles` serves
it through Golit's `/gis/tiles` route: rio-tiler reads only the z/x/y window each MapLibre
request needs — low zooms read the overviews, high zooms the native tiles — so the full
raster never crosses the wire. A colormap select and opacity slider re-render *only* the
map node; the `about` view depends on the path, so it stays put.

    pip install "golit[gis,gis-tiles]"
    golit run examples/tiled_raster/app.py
"""

from __future__ import annotations

import os
import tempfile

import golit.gis as gis
import golit.ui as ui
import numpy as np
import rasterio
from golit import App, create_app, select, slider
from rasterio.enums import Resampling
from rasterio.transform import from_bounds

_W, _S, _E, _N = -0.40, 5.45, 0.10, 5.80
_COG = os.path.join(tempfile.gettempdir(), "golit_tiled_demo.tif")


def _ensure_cog() -> str:
    """Write the demo COG once (tiled + overviews so rio-tiler reads it efficiently)."""
    if os.path.exists(_COG):
        return _COG
    size = 2000
    ys = np.linspace(_N, _S, size)  # north-first rows
    xs = np.linspace(_W, _E, size)
    xx, yy = np.meshgrid(xs, ys)

    def hill(cx: float, cy: float, height: float, spread: float) -> np.ndarray:
        return height * np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * spread**2)))

    elev = (hill(-0.20, 5.62, 820, 0.06) + hill(0.02, 5.71, 520, 0.045) + 60).astype("float32")
    with rasterio.open(
        _COG, "w", driver="GTiff", height=size, width=size, count=1, dtype="float32",
        crs="EPSG:4326", transform=from_bounds(_W, _S, _E, _N, size, size),
        tiled=True, blockxsize=256, blockysize=256, compress="deflate",
    ) as dst:
        dst.write(elev, 1)
        dst.build_overviews([2, 4, 8, 16], Resampling.average)
    return _COG


app = App(title="Tiled Raster Explorer")


@app.source
def cog() -> str:
    return _ensure_cog()


@app.view
def map(
    cog: str,
    cmap: str = select(["terrain", "viridis", "magma", "gist_earth"], default="terrain",
                       label="Colormap"),
    opacity: int = slider(40, 100, default=90, step=5, label="Opacity %"),
):
    # A tiled layer — recomputed only when cmap/opacity change; the tiles stream on demand.
    return gis.tiles(cog, cmap=cmap, opacity=opacity / 100, height="480px")


@app.view
def about(cog: str) -> str:
    # Depends only on the path — untouched when the controls move.
    with rasterio.open(cog) as src:
        width, height, overviews = src.width, src.height, src.overviews(1)
    return ui.columns(
        [
            ui.metric("Raster", f"{width}×{height}"),
            ui.metric("Megapixels", f"{width * height / 1e6:.1f}"),
            ui.metric("Overviews", str(len(overviews))),
        ]
    )


application = create_app(app)
