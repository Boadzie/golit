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


def test_geo_map_style_url_basemap_overlays_the_data() -> None:
    url = "https://demotiles.maplibre.org/style.json"
    spec = _spec_of(gis.geo_map(_squares(), basemap=url, color="revenue"))
    # A remote style can't be merged server-side, so the data rides in `overlay`.
    assert spec["style"] == url
    assert spec["overlay"]["sources"]["golit-geo"]["type"] == "geojson"
    assert any(layer["id"] == "golit-geo" for layer in spec["overlay"]["layers"])


def test_geo_map_preset_basemap_still_bakes_data_into_the_style() -> None:
    spec = _spec_of(gis.geo_map(_squares(), basemap="light"))
    assert spec["style"]["sources"]["golit-geo"]["type"] == "geojson"
    assert "overlay" not in spec


def test_geo_map_fit_padding_is_emitted_only_when_non_default() -> None:
    assert _spec_of(gis.geo_map(_squares(), fit_padding=60))["fitPadding"] == 60
    assert "fitPadding" not in _spec_of(gis.geo_map(_squares()))


def test_geo_map_hover_tooltip_trigger() -> None:
    spec = _spec_of(gis.geo_map(_squares(), tooltip=["name"], tooltip_trigger="hover"))
    assert spec["tooltipTrigger"] == "hover"
    # click is the default and stays implicit
    assert "tooltipTrigger" not in _spec_of(gis.geo_map(_squares(), tooltip=["name"]))


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
    assert "spec.overlay" in shell  # vector style-URL data overlay path
    assert "tooltipTrigger" in shell  # hover/click tooltips


def test_geo_map_numeric_color_overlays_a_gradient_legend() -> None:
    out = gis.geo_map(_squares(), color="revenue")
    assert out.strip().startswith('<div class="golit-map-wrap relative"')
    assert "golit-map-legend" in out
    assert "linear-gradient" in out  # numeric -> gradient bar
    assert "revenue" in out  # legend titled by the column


def test_geo_map_categorical_color_legend_has_one_swatch_per_value() -> None:
    out = gis.geo_map(_squares(), color="name")
    assert "golit-map-legend" in out
    assert out.count("width:10px;height:10px") == 2  # one swatch per distinct value


def test_geo_map_legend_off_and_no_color_have_no_legend() -> None:
    assert "golit-map-legend" not in gis.geo_map(_squares(), color="revenue", legend=False)
    assert "golit-map-legend" not in gis.geo_map(_squares())  # no color -> no legend


def test_geo_map_non_geo_frame_without_geometry_raises() -> None:
    import polars as pl

    with pytest.raises(TypeError):
        gis.geo_map(pl.DataFrame({"a": [1]}))


def test_to_geo_parses_wkt_geometry_to_a_geodataframe() -> None:
    import polars as pl

    frame = pl.DataFrame({"name": ["A"], "geometry": ["POINT (1 2)"]})
    gdf = gis.to_geo(frame, geometry="geometry")
    assert gis.is_geodataframe(gdf)
    assert str(gdf.crs).endswith("4326")
    assert gdf.geometry.iloc[0].wkt == "POINT (1 2)"
    assert "name" in gdf.columns


def test_spatial_sql_runs_st_functions() -> None:
    pytest.importorskip("duckdb")
    import polars as pl

    try:
        out = gis.spatial_sql("SELECT ST_AsText(ST_Point(1, 2)) AS p")
    except Exception as exc:  # noqa: BLE001 - extension download needs network
        pytest.skip(f"DuckDB spatial extension unavailable: {exc}")
    assert isinstance(out, pl.DataFrame)
    assert out.to_dicts() == [{"p": "POINT (1 2)"}]


def test_spatial_sql_to_geo_to_map_seam() -> None:
    pytest.importorskip("duckdb")
    try:
        frame = gis.spatial_sql(
            "SELECT 'A' AS name, 5 AS v, "
            "ST_AsWKB(ST_GeomFromText('POLYGON((0 0,1 0,1 1,0 1,0 0))')) AS geom"
        )
    except Exception as exc:  # noqa: BLE001 - extension download needs network
        pytest.skip(f"DuckDB spatial extension unavailable: {exc}")
    # spatial_sql returns a Polars frame with a WKB geometry column; geometry= bridges it.
    out = gis.geo_map(frame, geometry="geom", color="v")
    spec = _spec_of(out)
    assert spec["style"]["sources"]["golit-geo"]["data"]["type"] == "FeatureCollection"
