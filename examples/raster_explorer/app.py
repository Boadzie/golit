"""Raster Explorer — a reactive raster map (GIS phase 2).

A synthetic georeferenced "elevation" surface (an xarray DataArray over a Greater-Accra
bbox). A colormap select and an opacity slider feed ``gis.raster``, which colormaps the
band to a PNG and overlays it on a MapLibre basemap. Moving a control re-runs *only* the
map node — the ``stats`` view depends on the raw array, so it never re-renders.

    pip install "golit[gis,gis-raster]"
    golit run examples/raster_explorer/app.py
"""

from __future__ import annotations

import golit.gis as gis
import golit.ui as ui
import numpy as np
import rioxarray  # noqa: F401  (registers the .rio accessor used below)
import xarray as xr
from golit import App, create_app, select, slider

app = App(title="Raster Explorer")

# A georeferenced elevation surface: two Gaussian hills over a Greater-Accra bbox.
_W, _S, _E, _N = -0.40, 5.45, 0.10, 5.80
_YS = np.linspace(_N, _S, 160)  # north-first so row 0 is the north edge
_XS = np.linspace(_W, _E, 200)
_XX, _YY = np.meshgrid(_XS, _YS)


def _hill(cx: float, cy: float, height: float, spread: float) -> np.ndarray:
    return height * np.exp(-(((_XX - cx) ** 2 + (_YY - cy) ** 2) / (2 * spread**2)))


_ELEV = xr.DataArray(
    (_hill(-0.20, 5.62, 820, 0.06) + _hill(0.02, 5.71, 520, 0.045) + 60).astype(float),
    dims=("y", "x"),
    coords={"y": _YS, "x": _XS},
).rio.write_crs("EPSG:4326")

CMAPS = ["terrain", "viridis", "magma", "greys"]


@app.source
def elevation() -> xr.DataArray:
    return _ELEV


@app.view
def map(
    elevation: xr.DataArray,
    cmap: str = select(CMAPS, default="terrain", label="Colormap"),
    opacity: int = slider(20, 100, default=85, step=5, label="Opacity %"),
):
    # A native raster layer — recomputed only when cmap/opacity change.
    return gis.raster(
        elevation,
        cmap=cmap,
        opacity=opacity / 100,
        label="Elevation (m)",
        height="480px",
    )


@app.view
def stats(elevation: xr.DataArray) -> str:
    # Depends only on the array — untouched when the controls move.
    values = elevation.values
    return ui.columns(
        [
            ui.metric("Min", f"{values.min():.0f} m"),
            ui.metric("Max", f"{values.max():.0f} m"),
            ui.metric("Mean", f"{values.mean():.0f} m"),
        ]
    )


application = create_app(app)
