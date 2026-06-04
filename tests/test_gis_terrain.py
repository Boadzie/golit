"""GIS phase 3: terrain analysis — gis.terrain runs a WhiteboxTools operation on a DEM and
returns a georeferenced DataArray that feeds gis.raster.

Needs whitebox + rioxarray (skipped without them). The actual WhiteboxTools run downloads a
binary on first use, so the run tests skip cleanly when that's unavailable (offline). The
input-validation tests don't touch the binary."""

from __future__ import annotations

import html
import json

import pytest

pytest.importorskip("whitebox")
pytest.importorskip("rioxarray")
pytest.importorskip("rasterio")

import numpy as np  # noqa: E402
import rioxarray  # noqa: E402, F401  (registers the .rio accessor used in _dem)
import xarray as xr  # noqa: E402
from golit import gis  # noqa: E402


def _dem(size: int = 60, crs: str | None = "EPSG:32630") -> xr.DataArray:
    """A small projected-metres DEM (a hill) — UTM so slope/hillshade are meaningful."""
    res, x0, y0 = 30.0, 700000.0, 600000.0
    xs = x0 + np.arange(size) * res
    ys = (y0 + np.arange(size) * res)[::-1]  # descending y (north-up)
    xx, yy = np.meshgrid(xs, ys)
    cx, cy = x0 + size * res / 2, y0 + size * res / 2
    dem = (800 * np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 400.0**2))) + 60).astype(
        "float32"
    )
    da = xr.DataArray(dem, dims=("y", "x"), coords={"y": ys, "x": xs})
    return da.rio.write_crs(crs) if crs else da


def test_terrain_rejects_a_bare_numpy_array() -> None:
    with pytest.raises(TypeError):
        gis.terrain(np.zeros((4, 4)), "hillshade")  # no georeferencing -> no cell size


def test_terrain_dataarray_without_crs_raises() -> None:
    with pytest.raises(ValueError):
        gis.terrain(_dem(crs=None), "hillshade")  # needs a CRS for the transform


def _run_or_skip(dem: xr.DataArray, op: str, **params):
    try:
        return gis.terrain(dem, op, **params)
    except Exception as exc:  # noqa: BLE001 - WBT binary download needs network
        pytest.skip(f"WhiteboxTools unavailable: {type(exc).__name__}: {exc}")


def test_terrain_hillshade_returns_a_georeferenced_dataarray() -> None:
    dem = _dem()
    out = _run_or_skip(dem, "hillshade", azimuth=315, altitude=30)
    assert gis.is_dataarray(out)
    assert out.shape == dem.shape  # same grid
    assert out.rio.crs is not None and out.rio.crs.to_epsg() == 32630  # CRS preserved


def test_terrain_slope_result_feeds_raster() -> None:
    out = _run_or_skip(_dem(), "slope")
    fragment = gis.raster(out, cmap="magma", label="Slope (°)")
    # a georeferenced DataArray renders as a MapLibre image-layer map
    assert 'data-chart-lib="maplibre"' in fragment
    marker = 'data-chart-spec="'
    spec = json.loads(
        html.unescape(fragment[fragment.index(marker) + len(marker) :].split('"', 1)[0])
    )
    assert (spec.get("overlay") or spec["style"])["sources"]["golit-raster"]["type"] == "image"


def test_terrain_unknown_op_raises() -> None:
    # An unknown tool name surfaces as a ValueError (after the binary is available).
    dem = _dem()
    try:
        gis.terrain(dem, "definitely_not_a_wbt_tool")
    except ValueError:
        pass
    except Exception as exc:  # noqa: BLE001 - WBT binary download needs network
        pytest.skip(f"WhiteboxTools unavailable: {type(exc).__name__}: {exc}")
    else:
        pytest.fail("expected ValueError for an unknown WhiteboxTools tool")
