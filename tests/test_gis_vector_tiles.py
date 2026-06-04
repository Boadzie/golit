"""GIS phase 2.5: vector tiles — gis.vector_tiles emits a MapLibre vector source, and the
/gis/vector route encodes z/x/y MVT tiles from a server-side GeoDataFrame.

Needs mapbox-vector-tile + geopandas/shapely (skipped without them). No network. The
lazy-import test runs in a subprocess so importing this module's mapbox_vector_tile doesn't
mask a leaked top-level import in golit."""

from __future__ import annotations

import html
import json
import math
import re
import subprocess
import sys

import pytest

pytest.importorskip("mapbox_vector_tile")
gpd = pytest.importorskip("geopandas")
pytest.importorskip("shapely")

import mapbox_vector_tile as mvt  # noqa: E402
from golit import gis  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402


def _spec_of(fragment: str) -> dict:
    marker = 'data-chart-spec="'
    start = fragment.index(marker) + len(marker)
    end = fragment.index('"', start)
    return json.loads(html.unescape(fragment[start:end]))


def _container(spec: dict) -> dict:
    return spec.get("overlay") or spec["style"]


def _source(spec: dict) -> dict:
    return _container(spec)["sources"]["golit-geo"]


def _xyz(lon: float, lat: float, z: int) -> tuple[int, int, int]:
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return z, x, y


def _grid(rows: int = 4, cols: int = 3) -> gpd.GeoDataFrame:
    polys, names, vals = [], [], []
    for i in range(rows):
        for j in range(cols):
            x0, y0 = -0.30 + i * 0.10, 5.50 + j * 0.10
            polys.append(Polygon([(x0, y0), (x0 + 0.1, y0), (x0 + 0.1, y0 + 0.1), (x0, y0 + 0.1)]))
            names.append(f"c{i}{j}")
            vals.append(i * 10 + j)
    return gpd.GeoDataFrame({"name": names, "value": vals, "geometry": polys}, crs="EPSG:4326")


def test_vector_tiles_emits_a_vector_tile_source() -> None:
    spec = _spec_of(gis.vector_tiles(_grid(), color="value", tooltip=["name", "value"]))
    source = _source(spec)
    assert source["type"] == "vector"
    assert source["tiles"][0].startswith("/gis/vector/")
    assert "{z}/{x}/{y}" in source["tiles"][0]
    # the data layer targets the MVT layer name, not an inline GeoJSON source
    assert any(layer.get("source-layer") == "golit" for layer in _container(spec)["layers"])
    assert spec["bounds"][0][0] == pytest.approx(-0.30, abs=1e-3)
    assert spec["tooltip"] == ["name", "value"]


def test_vector_tiles_numeric_color_legend_and_choropleth() -> None:
    out = gis.vector_tiles(_grid(), color="value")
    spec = _spec_of(out)
    fill = next(layer for layer in _container(spec)["layers"] if layer["id"] == "golit-geo")
    assert fill["paint"]["fill-color"][0] == "interpolate"  # numeric -> choropleth ramp
    assert "golit-map-legend" in out  # gradient legend overlaid


def test_vector_tiles_token_is_stable_for_the_same_data() -> None:
    a = _source(_spec_of(gis.vector_tiles(_grid(), color="value")))["tiles"][0]
    b = _source(_spec_of(gis.vector_tiles(_grid(), color="value")))["tiles"][0]
    assert a == b  # identical data + params -> one registry slot, not a leak per render


def test_vector_tiles_points_and_lines_pick_circle_and_line_layers() -> None:
    pts = gpd.GeoDataFrame({"k": ["a"], "geometry": [Point(-0.2, 5.6)]}, crs="EPSG:4326")
    assert _container(_spec_of(gis.vector_tiles(pts)))["layers"][0]["type"] == "circle"
    lines = gpd.GeoDataFrame(
        {"k": ["a"], "geometry": [LineString([(-0.2, 5.6), (-0.1, 5.65)])]}, crs="EPSG:4326"
    )
    assert _container(_spec_of(gis.vector_tiles(lines)))["layers"][0]["type"] == "line"


def test_vector_tiles_non_geo_frame_without_geometry_raises() -> None:
    import polars as pl

    with pytest.raises(TypeError):
        gis.vector_tiles(pl.DataFrame({"a": [1]}))


def _make_client(gdf: gpd.GeoDataFrame):
    from golit import App, create_app
    from litestar.testing import TestClient

    app = App(title="VT")

    @app.view
    def m() -> str:
        return gis.vector_tiles(gdf, color="value")

    return TestClient(app=create_app(app))


def test_vector_route_serves_decodable_mvt_and_status_codes() -> None:
    gdf = _grid()
    with _make_client(gdf) as client:
        page = client.get("/")
        assert page.status_code == 200
        token = re.search(r"/gis/vector/([0-9a-f]{16})/", page.text).group(1)

        z, x, y = _xyz(-0.2, 5.6, 10)
        ok = client.get(f"/gis/vector/{token}/{z}/{x}/{y}")
        assert ok.status_code == 200
        assert ok.headers["content-type"].startswith("application/vnd.mapbox-vector-tile")
        decoded = mvt.decode(ok.content)
        features = decoded["golit"]["features"]
        assert features  # the tile carries features
        assert set(features[0]["properties"]) == {"name", "value"}  # properties preserved

        assert client.get(f"/gis/vector/{token}/10/0/0").status_code == 204  # empty -> blank
        assert client.get(f"/gis/vector/0000000000000000/{z}/{x}/{y}").status_code == 404


def test_importing_golit_does_not_import_mapbox_vector_tile() -> None:
    code = (
        "import sys, golit\n"
        "from golit import App, create_app\n"
        "create_app(App(title='x'))\n"
        "assert 'mapbox_vector_tile' not in sys.modules, 'mvt imported eagerly'\n"
        "print('ok')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "ok" in out.stdout
