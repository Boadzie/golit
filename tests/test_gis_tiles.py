"""GIS phase 2.5: tiled rasters — gis.tiles emits a MapLibre raster tile source, and the
/gis/tiles route serves z/x/y PNGs from a COG via rio-tiler.

Needs rio-tiler + rasterio (skipped without them). A small GeoTIFF is generated per test;
no network. The lazy-import test runs in a subprocess so importing this module's rio_tiler
doesn't mask a leaked top-level import in golit."""

from __future__ import annotations

import html
import json
import re
import subprocess
import sys

import pytest

pytest.importorskip("rio_tiler")
pytest.importorskip("rasterio")

import morecantile  # noqa: E402  (a rio-tiler dependency)
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from golit import gis  # noqa: E402
from rasterio.transform import from_bounds  # noqa: E402

_BBOX = (-0.40, 5.45, 0.10, 5.80)  # a Greater-Accra bbox, EPSG:4326


def _spec_of(fragment: str) -> dict:
    marker = 'data-chart-spec="'
    start = fragment.index(marker) + len(marker)
    end = fragment.index('"', start)
    return json.loads(html.unescape(fragment[start:end]))


def _container(spec: dict) -> dict:
    return spec.get("overlay") or spec["style"]


def _raster_source(spec: dict) -> dict:
    return _container(spec)["sources"]["golit-raster"]


@pytest.fixture
def cog(tmp_path) -> str:
    """A small single-band GeoTIFF (a ramp) over the bbox — rio-tiler reads it like a COG."""
    w, s, e, n = _BBOX
    size = 256
    data = (np.add.outer(np.linspace(0, 1, size), np.linspace(0, 1, size)) * 500).astype(
        "float32"
    )
    path = tmp_path / "scene.tif"
    with rasterio.open(
        path, "w", driver="GTiff", height=size, width=size, count=1, dtype="float32",
        crs="EPSG:4326", transform=from_bounds(w, s, e, n, size, size),
    ) as dst:
        dst.write(data, 1)
    return str(path)


def test_tiles_emits_a_raster_tile_source(cog: str) -> None:
    spec = _spec_of(gis.tiles(cog, cmap="terrain"))
    source = _raster_source(spec)
    assert source["type"] == "raster"
    assert source["tiles"][0].startswith("/gis/tiles/")
    assert "{z}/{x}/{y}" in source["tiles"][0]
    assert source["tileSize"] == 256
    assert "minzoom" in source and "maxzoom" in source
    # the camera frames the COG's geographic footprint
    assert spec["bounds"][0][0] == pytest.approx(-0.40)
    assert spec["bounds"][1][0] == pytest.approx(0.10, abs=1e-6)


def test_tiles_unknown_cmap_raises(cog: str) -> None:
    with pytest.raises(ValueError):
        gis.tiles(cog, cmap="definitely-not-a-colormap")


def test_tiles_token_is_stable_for_the_same_source(cog: str) -> None:
    a = _raster_source(_spec_of(gis.tiles(cog, cmap="terrain")))["tiles"][0]
    b = _raster_source(_spec_of(gis.tiles(cog, cmap="terrain")))["tiles"][0]
    assert a == b  # same path + params -> one registry slot, not a leak per render


def _covering_tile(cog: str) -> tuple[int, int, int]:
    from rio_tiler.io import Reader

    with Reader(cog) as src:
        z = src.minzoom
    w, s, e, n = _BBOX
    t = morecantile.tms.get("WebMercatorQuad").tile((w + e) / 2, (s + n) / 2, z)
    return z, t.x, t.y


def test_tile_route_serves_png_and_404s(cog: str) -> None:
    from golit import App, create_app
    from litestar.testing import TestClient

    app = App(title="Tiles")

    @app.view
    def scene() -> str:
        return gis.tiles(cog, cmap="terrain")

    with TestClient(app=create_app(app)) as client:
        page = client.get("/")
        assert page.status_code == 200
        token = re.search(r"/gis/tiles/([0-9a-f]{16})/", page.text).group(1)

        z, x, y = _covering_tile(cog)
        ok = client.get(f"/gis/tiles/{token}/{z}/{x}/{y}")
        assert ok.status_code == 200
        assert ok.content[:8] == b"\x89PNG\r\n\x1a\n"  # a real PNG tile

        assert client.get(f"/gis/tiles/0000000000000000/{z}/{x}/{y}").status_code == 404
        assert client.get(f"/gis/tiles/{token}/{z}/0/0").status_code == 404  # outside bounds


def test_importing_golit_does_not_import_rio_tiler() -> None:
    # The gis-tiles dependency must stay lazy: importing golit and building an app must not
    # pull in rio_tiler (it loads only when a tile is actually served).
    code = (
        "import sys, golit\n"
        "from golit import App, create_app\n"
        "create_app(App(title='x'))\n"
        "assert 'rio_tiler' not in sys.modules, 'rio_tiler imported eagerly'\n"
        "print('ok')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "ok" in out.stdout
