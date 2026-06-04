"""RGB Composite Explorer — a reactive true/false-color satellite view (GIS phase 2.5).

A synthetic 4-band "scene" (Red, Green, Blue, NIR) over a Greater-Accra bbox, with a
vegetation patch that is bright in the near-infrared. A band-combo select and a gamma
slider feed ``gis.rgb``, which stretches the chosen three bands and overlays the RGB
composite on a MapLibre basemap. Switching to a false-color combo lights up the
vegetation — the classic reason to look past natural color.

Moving a control re-runs *only* the map node; the ``stats`` view depends on the raw
array, so it never re-renders.

    pip install "golit[gis,gis-raster]"
    golit run examples/rgb_composite/app.py
"""

from __future__ import annotations

import golit.gis as gis
import golit.ui as ui
import numpy as np
import rioxarray  # noqa: F401  (registers the .rio accessor used below)
import xarray as xr
from golit import App, create_app, select, slider

app = App(title="RGB Composite Explorer")

# A georeferenced bbox over Greater Accra; north-first rows so row 0 is the north edge.
_W, _S, _E, _N = -0.40, 5.45, 0.10, 5.80
_YS = np.linspace(_N, _S, 180)
_XS = np.linspace(_W, _E, 240)
_XX, _YY = np.meshgrid(_XS, _YS)


def _blob(cx: float, cy: float, spread: float) -> np.ndarray:
    return np.exp(-(((_XX - cx) ** 2 + (_YY - cy) ** 2) / (2 * spread**2)))


# Three land-cover regions drive four reflectance-ish bands (0..1). Vegetation is bright
# in NIR and green; water is bright in blue and dark in NIR; bare soil is bright in red.
_veg = _blob(-0.18, 5.62, 0.05) + _blob(0.02, 5.71, 0.04)
_water = _blob(-0.31, 5.52, 0.03)
_soil = _blob(0.06, 5.55, 0.06)

_red = 0.12 + 0.34 * _soil + 0.04 * _veg
_green = 0.14 + 0.20 * _soil + 0.30 * _veg
_blue = 0.16 + 0.08 * _soil + 0.34 * _water
_nir = 0.10 + 0.78 * _veg + 0.05 * _soil

_DN = (np.stack([_red, _green, _blue, _nir]).clip(0, 1) * 4000).astype(float)  # 12-bit-ish
_SCENE = xr.DataArray(
    _DN, dims=("band", "y", "x"), coords={"band": [1, 2, 3, 4], "y": _YS, "x": _XS}
).rio.write_crs("EPSG:4326")

# Band combos as (R, G, B) source-band indices into the 4-band stack.
COMBOS = {
    "Natural (R·G·B)": (0, 1, 2),
    "False color (NIR·R·G)": (3, 0, 1),
    "Agriculture (NIR·R·B)": (3, 0, 2),
}


@app.source
def scene() -> xr.DataArray:
    return _SCENE


@app.view
def map(
    scene: xr.DataArray,
    combo: str = select(list(COMBOS), default="Natural (R·G·B)", label="Band combo"),
    gamma: int = slider(50, 200, default=100, step=10, label="Gamma %"),
):
    # An RGB composite layer — recomputed only when combo/gamma change.
    return gis.rgb(scene, bands=COMBOS[combo], gamma=gamma / 100, height="480px")


@app.view
def stats(scene: xr.DataArray) -> str:
    # Depends only on the array — untouched when the controls move.
    return ui.columns(
        [
            ui.metric("Bands", str(scene.sizes["band"])),
            ui.metric("Width", str(scene.sizes["x"])),
            ui.metric("Height", str(scene.sizes["y"])),
        ]
    )


application = create_app(app)
