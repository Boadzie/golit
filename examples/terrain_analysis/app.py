"""Terrain Analysis — reactive WhiteboxTools terrain on a DEM (GIS phase 3).

A synthetic projected DEM (two hills plus rolling texture, in UTM metres so slope and
hillshade are meaningful). An operation select and a sun-azimuth slider feed `gis.terrain`,
which runs WhiteboxTools and returns a georeferenced DataArray; `gis.raster` then overlays
it on a MapLibre basemap with an operation-appropriate colormap. Moving a control re-runs
*only* the relief view; the `info` view depends on the raw DEM, so it stays put.

WhiteboxTools downloads its binary on first use.

    pip install "golit[gis,gis-terrain]"
    golit run examples/terrain_analysis/app.py
"""

from __future__ import annotations

import golit.gis as gis
import golit.ui as ui
import numpy as np
import rioxarray  # noqa: F401  (registers the .rio accessor used below)
import xarray as xr
from golit import App, create_app, select, slider

# A projected DEM (UTM 30N, 30 m cells) so terrain analysis has a real cell size.
_SIZE, _RES, _X0, _Y0 = 300, 30.0, 700000.0, 600000.0
_XS = _X0 + np.arange(_SIZE) * _RES
_YS = (_Y0 + np.arange(_SIZE) * _RES)[::-1]  # descending y (north-up)
_XX, _YY = np.meshgrid(_XS, _YS)
_CX, _CY = _X0 + _SIZE * _RES / 2, _Y0 + _SIZE * _RES / 2


def _hill(cx: float, cy: float, height: float, spread: float) -> np.ndarray:
    return height * np.exp(-(((_XX - cx) ** 2 + (_YY - cy) ** 2) / (2 * spread**2)))


_DEM = xr.DataArray(
    (
        _hill(_CX - 1500, _CY - 1000, 600, 1200)
        + _hill(_CX + 1800, _CY + 1200, 800, 1500)
        + 50 * np.sin(_XX / 800) * np.cos(_YY / 700)
        + 100
    ).astype("float32"),
    dims=("y", "x"),
    coords={"y": _YS, "x": _XS},
).rio.write_crs("EPSG:32630")

_CMAP = {"hillshade": "greys", "slope": "magma", "aspect": "viridis"}

app = App(title="Terrain Analysis")


@app.source
def dem() -> xr.DataArray:
    return _DEM


@app.view
def relief(
    dem: xr.DataArray,
    op: str = select(["hillshade", "slope", "aspect"], default="hillshade", label="Operation"),
    azimuth: int = slider(0, 360, default=315, step=15, label="Sun azimuth"),
):
    # Run WhiteboxTools, then overlay the result — recomputed only when op/azimuth change.
    params = {"azimuth": azimuth, "altitude": 35} if op == "hillshade" else {}
    result = gis.terrain(dem, op, **params)
    return gis.raster(result, cmap=_CMAP[op], opacity=0.9, label=op.title(), height="480px")


@app.view
def info(dem: xr.DataArray) -> str:
    # Depends only on the DEM — untouched when the controls move.
    values = dem.values
    return ui.columns(
        [
            ui.metric("Min elev", f"{values.min():.0f} m"),
            ui.metric("Max elev", f"{values.max():.0f} m"),
            ui.metric("Cells", f"{values.size:,}"),
        ]
    )


application = create_app(app)
