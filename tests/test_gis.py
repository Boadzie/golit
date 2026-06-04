"""GIS phase 1: maplibre mounts, GeoDataFrame -> MapLibre maps, render routing,
geo hashing, DuckDB spatial SQL, and the shell's maplibre wiring.

Geometry tests need geopandas/shapely (skipped without them). The spatial-SQL test
also needs the `sql` extra and downloads the DuckDB spatial extension on first run, so
it skips cleanly when that's unavailable (e.g. offline)."""

from __future__ import annotations

import html
import json

import pytest
from golit import gis
from golit.rendering import render_value
from golit.rendering.html import page

gpd = pytest.importorskip("geopandas")
pytest.importorskip("shapely")
from shapely.geometry import LineString, Point, Polygon  # noqa: E402


def _spec_of(fragment: str) -> dict:
    """Pull the JSON spec back out of a mount's data-chart-spec attribute."""
    marker = 'data-chart-spec="'
    start = fragment.index(marker) + len(marker)
    end = fragment.index('"', start)
    return json.loads(html.unescape(fragment[start:end]))


def _geo_layer(spec: dict) -> dict:
    return next(layer for layer in spec["style"]["layers"] if layer["id"] == "golit-geo")


def _squares() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "name": ["A", "B"],
            "revenue": [120, 300],
            "geometry": [
                Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
            ],
        },
        crs="EPSG:4326",
    )


def test_maplibre_emits_maplibre_mount_with_camera() -> None:
    out = gis.maplibre(
        "https://demotiles.maplibre.org/style.json",
        center=[-0.2, 5.6],
        zoom=10,
        pitch=45,
    )
    assert 'class="golit-chart' in out
    assert 'data-chart-lib="maplibre"' in out
    spec = _spec_of(out)
    assert spec["style"] == "https://demotiles.maplibre.org/style.json"
    assert spec["center"] == [-0.2, 5.6]
    assert spec["zoom"] == 10
    assert spec["pitch"] == 45
    assert spec["height"] == "420px"


def test_maplibre_accepts_a_style_dict_and_passthrough_opts() -> None:
    style = {"version": 8, "sources": {}, "layers": []}
    spec = _spec_of(gis.maplibre(style, bounds=[[0, 0], [1, 1]], maxZoom=12))
    assert spec["style"] == style
    assert spec["bounds"] == [[0, 0], [1, 1]]
    assert spec["maxZoom"] == 12


def test_geo_map_polygon_builds_geojson_fill_layer_and_bounds() -> None:
    spec = _spec_of(gis.geo_map(_squares()))
    source = spec["style"]["sources"]["golit-geo"]
    assert source["type"] == "geojson"
    assert source["data"]["type"] == "FeatureCollection"
    assert len(source["data"]["features"]) == 2
    assert _geo_layer(spec)["type"] == "fill"
    assert spec["bounds"] == [[0.0, 0.0], [2.0, 1.0]]


def test_geo_map_numeric_color_is_an_interpolate_choropleth() -> None:
    expr = _geo_layer(_spec_of(gis.geo_map(_squares(), color="revenue")))["paint"]["fill-color"]
    assert expr[0] == "interpolate"
    assert expr[2] == ["get", "revenue"]


def test_geo_map_categorical_color_is_a_match_expression() -> None:
    expr = _geo_layer(_spec_of(gis.geo_map(_squares(), color="name")))["paint"]["fill-color"]
    assert expr[0] == "match"
    assert expr[1] == ["get", "name"]


def test_geo_map_tooltip_records_fields_and_layer() -> None:
    spec = _spec_of(gis.geo_map(_squares(), tooltip=["name", "revenue"]))
    assert spec["tooltip"] == ["name", "revenue"]
    assert spec["tooltipLayer"] == "golit-geo"
    # tooltip=True selects every non-geometry column.
    assert set(_spec_of(gis.geo_map(_squares(), tooltip=True))["tooltip"]) == {"name", "revenue"}


def test_geo_map_points_use_a_circle_layer() -> None:
    pts = gpd.GeoDataFrame({"k": ["x"], "geometry": [Point(0, 0)]}, crs="EPSG:4326")
    assert _geo_layer(_spec_of(gis.geo_map(pts)))["type"] == "circle"


def test_geo_map_lines_use_a_line_layer() -> None:
    lines = gpd.GeoDataFrame(
        {"k": ["x"], "geometry": [LineString([(0, 0), (1, 1)])]}, crs="EPSG:4326"
    )
    assert _geo_layer(_spec_of(gis.geo_map(lines)))["type"] == "line"


def test_geo_map_reprojects_to_4326() -> None:
    web_mercator = _squares().to_crs(epsg=3857)  # coords now in metres
    bounds = _spec_of(gis.geo_map(web_mercator))["bounds"]
    # Back in lon/lat after geo_map reprojects.
    assert bounds[0][0] == pytest.approx(0.0, abs=1e-6)
    assert bounds[1][0] == pytest.approx(2.0, abs=1e-6)


def test_geo_map_basemap_presets_and_none() -> None:
    assert _spec_of(gis.geo_map(_squares(), basemap="dark"))["style"]["sources"]["basemap"]
    no_base = _spec_of(gis.geo_map(_squares(), basemap="none"))
    assert no_base["style"]["layers"][0]["type"] == "background"
    with pytest.raises(ValueError):
        gis.geo_map(_squares(), basemap="bogus")


def test_render_value_routes_a_geodataframe_to_a_map_not_a_table() -> None:
    out = render_value(_squares())
    assert 'data-chart-lib="maplibre"' in out
    assert "golit-table" not in out  # not the pandas _repr_html_ table


def test_is_geodataframe_detects_without_false_positives() -> None:
    assert gis.is_geodataframe(_squares())
    assert not gis.is_geodataframe({"a": 1})
    assert not gis.is_geodataframe(_squares().geometry)  # a GeoSeries, not a frame


def test_geodataframe_hash_is_content_based() -> None:
    from golit.hashing import hash_value

    a = _squares()
    b = a.copy()
    c = a.copy()
    c.loc[0, "revenue"] = 999
    assert hash_value(a) == hash_value(b)  # same data -> memo hit
    assert hash_value(a) != hash_value(c)  # attribute change -> miss


def test_page_shell_carries_maplibre_cdn_and_css() -> None:
    shell = page("Maps", "<main></main>")
    assert "maplibre-gl@5.24.0/dist/maplibre-gl.js" in shell  # CDN runtime wired in
    assert "maplibre-gl@5.24.0/dist/maplibre-gl.css" in shell  # required stylesheet linked
    assert "drawMap" in shell  # the bootstrap can render a map mount


def test_spatial_sql_runs_st_functions() -> None:
    pytest.importorskip("duckdb")
    import polars as pl

    try:
        out = gis.spatial_sql("SELECT ST_AsText(ST_Point(1, 2)) AS p")
    except Exception as exc:  # noqa: BLE001 - extension download needs network
        pytest.skip(f"DuckDB spatial extension unavailable: {exc}")
    assert isinstance(out, pl.DataFrame)
    assert out.to_dicts() == [{"p": "POINT (1 2)"}]
