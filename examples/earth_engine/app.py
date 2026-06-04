"""Earth Engine Explorer — reactive Google Earth Engine imagery (GIS phase 3).

A Sentinel-2 surface-reflectance median composite over a Greater-Accra AOI. A cloud-cover
slider and a band-combo select feed `gis.ee_layer`, which asks Earth Engine for a tile URL
(`image.getMapId(vis)`) and overlays it as a MapLibre raster source — EE renders the tiles
on its servers, so moving a control just swaps in a new tile URL.

Unlike the other GIS examples, this one needs a **Google Earth Engine account**: authenticate
once and point it at a Cloud project.

    pip install "golit[gis,gis-ee]"
    earthengine authenticate                 # one-time, opens a browser
    export EE_PROJECT=your-cloud-project      # an EE-enabled Google Cloud project
    golit run examples/earth_engine/app.py
"""

from __future__ import annotations

import os

import ee
import golit.gis as gis
from golit import App, create_app, select, slider

# Authenticate first (`earthengine authenticate`); EE_PROJECT is an EE-enabled Cloud project.
ee.Initialize(project=os.environ.get("EE_PROJECT"))

app = App(title="Earth Engine Explorer")

_AOI = ee.Geometry.Rectangle([-0.40, 5.45, 0.10, 5.80])  # Greater Accra
_VIS = {
    "Natural (RGB)": {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000},
    "False color (NIR)": {"bands": ["B8", "B4", "B3"], "min": 0, "max": 4000},
    "Agriculture": {"bands": ["B11", "B8", "B2"], "min": 0, "max": 4000},
}


@app.view
def scene(
    cloud: int = slider(5, 80, default=30, step=5, label="Max cloud %"),
    combo: str = select(list(_VIS), default="Natural (RGB)", label="Bands"),
):
    # A cloud-filtered median composite — recomputed (a new EE tile URL) on control change.
    composite = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(_AOI)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud))
        .median()
        .clip(_AOI)
    )
    return gis.ee_layer(composite, vis=_VIS[combo], center=[-0.15, 5.62], zoom=10, height="520px")


application = create_app(app)
