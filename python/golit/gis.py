"""GIS — reactive maps as ordinary Golit views.

A map is a view like any other: return one from an ``@app.view`` node and a control
that touches its inputs rebuilds *only* that view. Phase 1 covers vector data and
native MapLibre GL rendering plus DuckDB spatial SQL:

* :func:`maplibre` — a native, GPU vector map from a style (URL or dict) and a camera;
* :func:`geo_map` — a GeoDataFrame straight to a MapLibre choropleth/line/point map
  (a view may also just *return* the GeoDataFrame — see :func:`golit.rendering.render_value`);
* :func:`vector_tiles` — a *large* GeoDataFrame served as on-demand MVT vector tiles (the
  data stays server-side; only the visible tiles cross the wire — the vector analog of
  :func:`tiles`);
* :func:`explore` — the folium/leafmap escape hatch (``gdf.explore`` embedded as-is);
* :func:`spatial_sql` — DuckDB ``ST_*`` SQL over Polars/GeoJSON sources, returning Polars.

Raster (phases 2 / 2.5) overlays a georeferenced array as a native MapLibre image layer:

* :func:`raster` — a single band colormapped to a PNG (``cmap``, legend, nodata→transparent);
* :func:`rgb` — a multiband raster as a true/false-color RGB composite with per-band stretch;
* :func:`tiles` — a very large COG streamed as on-demand ``z/x/y`` tiles via rio-tiler
  (a server-side tile route; only the visible window crosses the wire).

Analysis (phase 3):

* :func:`terrain` — a WhiteboxTools terrain operation (hillshade/slope/flow…) on a DEM,
  returning a ``DataArray`` that feeds :func:`raster`/:func:`tiles`;
* :func:`ee_layer` — a Google Earth Engine image overlaid as live XYZ tiles (EE renders;
  Golit points a MapLibre raster source at the tile URL).

Everything heavy (GeoPandas, pyproj, folium, DuckDB) is imported lazily *inside* the
functions, so ``import golit`` — and therefore ``import golit.gis`` — never pulls them
in. Install the extra with ``pip install "golit[gis]"`` (DuckDB spatial rides on the
existing ``sql`` extra).
"""

from __future__ import annotations

import html as _html
import os
from typing import Any

import polars as pl

from .rendering.interactive import chart_spec

# Sequential blue ramp (brand primary #1565C0) for a numeric choropleth, and a
# qualitative palette for a categorical one. Both are emitted as MapLibre style
# expressions, so the GPU does the actual data→color mapping client-side.
_SEQUENTIAL = ["#eff6ff", "#bfdbfe", "#60a5fa", "#2563eb", "#1e3a8a"]
_CATEGORICAL = [
    "#1565c0", "#ef6c00", "#2e7d32", "#c62828", "#6a1b9a",
    "#00838f", "#9e9d24", "#4527a0", "#ad1457", "#5d4037",
]

# Basemap presets. Vector presets resolve to an OpenFreeMap style URL — free, no API
# key, OSM-based, weekly updates, self-hostable (https://openfreemap.org) — which geo_map
# overlays the data onto; the hosted style carries its own attribution. Raster presets
# (CARTO/OSM tile layers) stay available as an opt-in fallback. A dict basemap is used as
# a full style; "none" draws just a flat background so the data carries the map.
_OPENFREEMAP = "https://tiles.openfreemap.org/styles"
_VECTOR_BASEMAPS = {
    "default": "positron",  # light + neutral — the best backdrop under choropleth colors
    "positron": "positron",
    "light": "positron",
    "liberty": "liberty",
    "bright": "bright",
    "dark": "dark",
}
_CARTO_ATTR = "© OpenStreetMap, © CARTO"
_CARTO_LIGHT = "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"
_CARTO_DARK = "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
_RASTER_BASEMAPS = {
    "osm": ("https://tile.openstreetmap.org/{z}/{x}/{y}.png", "© OpenStreetMap contributors"),
    "carto-light": (_CARTO_LIGHT, _CARTO_ATTR),
    "carto-dark": (_CARTO_DARK, _CARTO_ATTR),
}

_SOURCE = "golit-geo"  # the GeoJSON/vector source + layer id geo_map/vector_tiles inject
_RASTER = "golit-raster"  # the image source/layer id raster() injects into the style
_VTILE_LAYER = "golit"  # the MVT layer name inside vector_tiles' tiles

# Colormaps for raster(), as anchor colors interpolated to a 256-entry LUT with numpy —
# dependency-free (no matplotlib). The same anchors drive the raster legend's gradient.
_RASTER_CMAPS = {
    "viridis": ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"],
    "magma": ["#000004", "#51127c", "#b73779", "#fc8961", "#fcfdbf"],
    "blues": ["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"],
    "terrain": ["#333399", "#0099cc", "#33cc66", "#ffff66", "#b35900", "#ffffff"],
    "greys": ["#ffffff", "#000000"],
}


def is_geodataframe(value: Any) -> bool:
    """Whether ``value`` is a GeoPandas ``GeoDataFrame`` — by class, without importing
    geopandas (mirrors the matplotlib/Lets-Plot detectors). Used by
    :func:`golit.rendering.render_value` and :func:`golit.hashing.hash_value` so a view
    can return a GeoDataFrame directly."""
    cls = type(value)
    return cls.__name__ == "GeoDataFrame" and (cls.__module__ or "").startswith("geopandas")


def maplibre(
    style: Any,
    *,
    center: Any = None,
    zoom: float | None = None,
    pitch: float = 0,
    bearing: float = 0,
    height: str = "420px",
    **opts: Any,
) -> str:
    """A native MapLibre GL map from a ``style`` and camera, as a reactive view fragment.

    ``style`` is either a style-URL string (e.g. a vector tile style) or a full MapLibre
    style ``dict`` (``{"version": 8, "sources": {...}, "layers": [...]}``). ``center`` is
    ``[lng, lat]``; ``zoom`` the zoom level; ``pitch``/``bearing`` tilt and rotate for a
    3D view (combine with a style carrying ``fill-extrusion`` or ``terrain`` layers). Extra
    keyword args (``minZoom``, ``maxZoom``, ``bounds``, …) pass straight to the map spec::

        @app.view
        def map(city):
            return gis.maplibre(
                "https://demotiles.maplibre.org/style.json",
                center=[city["lng"], city["lat"]], zoom=11, pitch=45,
            )

    Pure dict assembly — imports nothing. The mount hydrates on first paint and on every
    POST/SSE swap, and its WebGL context is freed when the fragment is replaced."""
    spec: dict[str, Any] = {"style": style, "height": height}
    if center is not None:
        spec["center"] = list(center)
    if zoom is not None:
        spec["zoom"] = zoom
    if pitch:
        spec["pitch"] = pitch
    if bearing:
        spec["bearing"] = bearing
    spec.update(opts)
    return chart_spec("maplibre", spec)


def _base_style(basemap: Any) -> dict[str, Any] | str:
    """The base MapLibre style geo_map layers onto: a style ``dict`` we can bake the data
    into, or a style-**URL** string (returned as-is — geo_map overlays the data on load,
    since a remote style can't be merged server-side)."""
    if isinstance(basemap, dict):
        style = dict(basemap)
        style.setdefault("version", 8)
        style.setdefault("sources", {})
        style.setdefault("layers", [])
        # Copy so we never mutate the caller's dict when appending the data layers.
        style["sources"] = dict(style["sources"])
        style["layers"] = list(style["layers"])
        return style
    if basemap in (None, "none"):
        background = {"id": "bg", "type": "background", "paint": {"background-color": "#eaeef2"}}
        return {"version": 8, "sources": {}, "layers": [background]}
    if isinstance(basemap, str):
        if basemap in _VECTOR_BASEMAPS:  # OpenFreeMap vector style → overlay path
            return f"{_OPENFREEMAP}/{_VECTOR_BASEMAPS[basemap]}"
        if basemap.startswith(("http://", "https://", "mapbox://")):
            return basemap  # a vector style URL — data overlaid after the style loads
        if basemap in _RASTER_BASEMAPS:
            tiles, attribution = _RASTER_BASEMAPS[basemap]
            source = {"type": "raster", "tiles": [tiles], "tileSize": 256,
                      "attribution": attribution}
            return {
                "version": 8,
                "sources": {"basemap": source},
                "layers": [{"id": "basemap", "type": "raster", "source": "basemap"}],
            }
    raise ValueError(
        f"unknown basemap {basemap!r}; vector: {sorted(_VECTOR_BASEMAPS)}, "
        f"raster: {sorted(_RASTER_BASEMAPS)}, or 'none' / a style dict / a style URL"
    )


def _color_mapping(gdf: Any, column: str) -> dict[str, Any]:
    """Map ``column`` to a MapLibre paint expression *and* the data a legend needs:
    an ``interpolate`` ramp for a numeric column (a choropleth), a ``match`` over
    distinct values for a categorical one. Computed once, reused by the layer and the
    legend so they can't drift."""
    from pandas.api.types import is_numeric_dtype

    series = gdf[column]
    if is_numeric_dtype(series):
        vmin = float(series.min())
        vmax = float(series.max())
        if vmin == vmax:
            vmax = vmin + 1.0
        last = len(_SEQUENTIAL) - 1
        expr: list[Any] = ["interpolate", ["linear"], ["get", column]]
        for i, color in enumerate(_SEQUENTIAL):
            expr.extend([vmin + (vmax - vmin) * i / last, color])
        return {"expr": expr, "kind": "numeric", "vmin": vmin, "vmax": vmax,
                "colors": _SEQUENTIAL}
    cats = list(dict.fromkeys(str(v) for v in series.tolist()))
    expr = ["match", ["get", column]]
    pairs: list[tuple[str, str]] = []
    for i, cat in enumerate(cats):
        color = _CATEGORICAL[i % len(_CATEGORICAL)]
        expr.extend([cat, color])
        pairs.append((cat, color))
    expr.append("#9ca3af")  # fallback for values not seen at build time
    return {"expr": expr, "kind": "categorical", "categories": pairs}


def _data_layers(
    gdf: Any, mapping: dict[str, Any] | None, source_layer: str | None = None
) -> list[dict[str, Any]]:
    """The fill/line/circle layer(s) for the data source, chosen by geometry type. With a
    ``source_layer`` the layers target a MapLibre *vector* source (the MVT layer name);
    without it they target an inline GeoJSON source (:func:`geo_map`)."""
    paint = mapping["expr"] if mapping else "#1565c0"
    kinds = {str(t).replace("Multi", "") for t in gdf.geom_type.dropna().unique()}
    if "Polygon" in kinds:
        layers = [
            {"id": _SOURCE, "type": "fill", "source": _SOURCE,
             "paint": {"fill-color": paint, "fill-opacity": 0.7}},
            {"id": f"{_SOURCE}-outline", "type": "line", "source": _SOURCE,
             "paint": {"line-color": "#ffffff", "line-width": 0.6}},
        ]
    elif "LineString" in kinds:
        layers = [
            {"id": _SOURCE, "type": "line", "source": _SOURCE,
             "paint": {"line-color": paint, "line-width": 2.5}},
        ]
    else:
        layers = [
            {"id": _SOURCE, "type": "circle", "source": _SOURCE,
             "paint": {"circle-color": paint, "circle-radius": 5,
                       "circle-stroke-color": "#ffffff", "circle-stroke-width": 1}},
        ]
    if source_layer is not None:
        for layer in layers:
            layer["source-layer"] = source_layer  # a vector source needs the MVT layer name
    return layers


def _fmt(value: float) -> str:
    """Compact number label for the legend (thousands-separated; integers stay integers)."""
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _legend_html(column: str, mapping: dict[str, Any]) -> str:
    """A small server-rendered legend overlaid on the map: a gradient bar for a numeric
    choropleth, color swatches for a categorical one. No client runtime — plain markup."""
    title = (
        '<p class="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant '
        f'mb-1">{_html.escape(column)}</p>'
    )
    if mapping["kind"] == "numeric":
        gradient = ", ".join(mapping["colors"])
        bar = (
            f'<div style="height:8px;border-radius:4px;background:linear-gradient('
            f'to right,{gradient})"></div>'
        )
        labels = (
            '<div class="flex justify-between text-[10px] text-on-surface-variant mt-1">'
            f'<span>{_fmt(mapping["vmin"])}</span><span>{_fmt(mapping["vmax"])}</span></div>'
        )
        body = bar + labels
    else:
        rows = "".join(
            '<div class="flex items-center gap-1.5">'
            f'<span style="width:10px;height:10px;border-radius:2px;background:{color}"></span>'
            f'<span class="text-[10px]">{_html.escape(cat)}</span></div>'
            for cat, color in mapping["categories"]
        )
        body = f'<div class="flex flex-col gap-1">{rows}</div>'
    return (
        '<div class="golit-map-legend absolute bottom-3 left-3 z-10 bg-surface-container-lowest/90 '
        'backdrop-blur rounded-lg shadow-sm p-2.5 min-w-[120px] pointer-events-none">'
        f"{title}{body}</div>"
    )


def geo_map(
    gdf: Any,
    *,
    color: str | None = None,
    tooltip: Any = None,
    tooltip_trigger: str = "click",
    basemap: Any = "default",
    fit: bool = True,
    fit_padding: int = 24,
    legend: bool = True,
    geometry: str | None = None,
    height: str = "420px",
    **opts: Any,
) -> str:
    """Render a GeoPandas ``GeoDataFrame`` as a native MapLibre map.

    The frame is reprojected to EPSG:4326 if needed, serialized to GeoJSON, and added to
    a MapLibre style as a source with a fill (polygons), line (lines), or circle (points)
    layer picked from the geometry type. ``color`` names a column to drive the fill — a
    blue ramp for a numeric column (a choropleth), a categorical palette for a text one;
    when ``color`` is set, a ``legend`` is overlaid (gradient bar or swatches) unless
    turned off. ``tooltip`` shows feature properties: ``True`` for every attribute, or a
    column name / list of names — on click, or on hover with ``tooltip_trigger="hover"``.
    ``basemap`` is a vector preset (``"default"``/``"positron"``, ``"liberty"``,
    ``"bright"``, ``"dark"`` — free OpenFreeMap styles, no API key), a raster preset
    (``"osm"``, ``"carto-light"``, ``"carto-dark"``), ``"none"``, a full style ``dict``,
    or any style-**URL** string. With ``fit`` the camera frames the data (``fit_padding`` px)::

        @app.view
        def map(regions):                  # regions is a filtered GeoDataFrame
            return gis.geo_map(regions, color="revenue", tooltip=["name", "revenue"])

    A plain Polars/pandas frame works too if you name its geometry column with
    ``geometry=`` (WKB/WKT/shapely) — the bridge from :func:`spatial_sql`::

        return gis.geo_map(gis.spatial_sql("SELECT name, geom FROM p …", p=places),
                           geometry="geom", color="name")

    A view may also just ``return`` a GeoDataFrame — :func:`golit.rendering.render_value`
    routes it here with defaults. Requires ``pip install "golit[gis]"``."""
    import json

    if not is_geodataframe(gdf):
        if geometry is None:
            raise TypeError(
                "geo_map expects a GeoDataFrame, or a frame plus geometry=<column name>"
            )
        gdf = to_geo(gdf, geometry=geometry)

    crs = getattr(gdf, "crs", None)
    if crs is not None and crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    mapping = _color_mapping(gdf, color) if color else None
    geojson = json.loads(gdf.to_json())
    source = {"type": "geojson", "data": geojson}
    layers = _data_layers(gdf, mapping)

    base = _base_style(basemap)
    spec: dict[str, Any] = {"height": height}
    if isinstance(base, str):
        # vector style URL — overlay the data once the remote style finishes loading
        spec["style"] = base
        spec["overlay"] = {"sources": {_SOURCE: source}, "layers": layers}
    else:
        base["sources"][_SOURCE] = source
        base["layers"].extend(layers)
        spec["style"] = base

    if fit and "bounds" not in opts:
        minx, miny, maxx, maxy = (float(v) for v in gdf.total_bounds)
        spec["bounds"] = [[minx, miny], [maxx, maxy]]
        if fit_padding != 24:
            spec["fitPadding"] = fit_padding

    fields = _tooltip_fields(gdf, tooltip)
    if fields:
        spec["tooltip"] = fields
        spec["tooltipLayer"] = _SOURCE
        if tooltip_trigger != "click":
            spec["tooltipTrigger"] = tooltip_trigger

    spec.update(opts)
    mount = chart_spec("maplibre", spec)
    if legend and mapping is not None and color is not None:
        # Overlay the legend on the map; the relative wrapper anchors the absolute legend.
        return f'<div class="golit-map-wrap relative">{mount}{_legend_html(color, mapping)}</div>'
    return mount


def vector_tiles(
    gdf: Any,
    *,
    color: str | None = None,
    tooltip: Any = None,
    tooltip_trigger: str = "click",
    properties: Any = None,
    basemap: Any = "default",
    fit: bool = True,
    fit_padding: int = 24,
    legend: bool = True,
    geometry: str | None = None,
    min_zoom: int = 0,
    max_zoom: int = 14,
    height: str = "420px",
    **opts: Any,
) -> str:
    """Render a **large** ``GeoDataFrame`` as server-side **vector tiles** (GIS phase 2.5).

    Where :func:`geo_map` inlines the whole GeoJSON into the page — fine for thousands of
    features, not for hundreds of thousands — ``vector_tiles`` keeps the data **server-side**
    and streams only the features in each ``z/x/y`` tile as a Mapbox Vector Tile (MVT). The
    map looks the same (``color`` choropleth, ``tooltip`` popups, ``basemap``, ``legend``) but
    scales: nothing but the visible tiles crosses the wire, and the GPU styles the vector
    features client-side::

        @app.view
        def map(parcels):                          # parcels: a big GeoDataFrame
            return gis.vector_tiles(parcels, color="value", tooltip=["id", "value"])

    The frame is reprojected to Web Mercator and registered under an opaque token; the
    ``/gis/vector`` route encodes tiles on demand. ``properties`` limits which columns ride in
    the tiles (the ``color`` column and ``tooltip`` fields are always included); ``min_zoom`` /
    ``max_zoom`` bound the tile pyramid (MapLibre over-zooms past ``max_zoom``). A plain
    Polars/pandas frame works with ``geometry=<column>`` (as in :func:`geo_map`). Requires
    ``pip install "golit[gis,gis-vector-tiles]"``."""
    from .server.vector_tiles import register_source

    if not is_geodataframe(gdf):
        if geometry is None:
            raise TypeError(
                "vector_tiles expects a GeoDataFrame, or a frame plus geometry=<column name>"
            )
        gdf = to_geo(gdf, geometry=geometry)

    mapping = _color_mapping(gdf, color) if color else None

    # Columns to embed as MVT feature properties — everything by default, or an explicit list
    # plus whatever the choropleth/tooltips need so they keep working client-side.
    geom_name = gdf.geometry.name
    if properties is None:
        cols = [c for c in gdf.columns if c != geom_name]
    else:
        wanted = set(properties)
        if color:
            wanted.add(color)
        wanted.update(_tooltip_fields(gdf, tooltip) or [])
        cols = [c for c in gdf.columns if c != geom_name and c in wanted]

    crs = getattr(gdf, "crs", None)
    web = gdf.to_crs(epsg=3857) if crs is not None else gdf  # the tiling CRS (Web Mercator)

    from pyproj import Transformer

    to4326 = Transformer.from_crs(3857, 4326, always_xy=True)
    minx, miny, maxx, maxy = (float(v) for v in web.total_bounds)
    west, south = to4326.transform(minx, miny)
    east, north = to4326.transform(maxx, maxy)

    token = _tile_token("vector", len(web), sorted(map(str, cols)), color,
                        round(west, 5), round(south, 5), round(east, 5), round(north, 5),
                        min_zoom, max_zoom, _attrs_fingerprint(web, cols))
    register_source(token, {"gdf": web, "properties": cols, "layer": _VTILE_LAYER})

    source = {
        "type": "vector",
        "tiles": [f"/gis/vector/{token}/{{z}}/{{x}}/{{y}}"],
        "minzoom": min_zoom,
        "maxzoom": max_zoom,
    }
    layers = _data_layers(gdf, mapping, source_layer=_VTILE_LAYER)

    base = _base_style(basemap)
    spec: dict[str, Any] = {"height": height}
    if isinstance(base, str):
        spec["style"] = base
        spec["overlay"] = {"sources": {_SOURCE: source}, "layers": layers}
    else:
        base["sources"][_SOURCE] = source
        base["layers"].extend(layers)
        spec["style"] = base

    if fit and "bounds" not in opts:
        spec["bounds"] = [[west, south], [east, north]]
        if fit_padding != 24:
            spec["fitPadding"] = fit_padding

    fields = _tooltip_fields(gdf, tooltip)
    if fields:
        spec["tooltip"] = fields
        spec["tooltipLayer"] = _SOURCE
        if tooltip_trigger != "click":
            spec["tooltipTrigger"] = tooltip_trigger

    spec.update(opts)
    mount = chart_spec("maplibre", spec)
    if legend and mapping is not None and color is not None:
        return f'<div class="golit-map-wrap relative">{mount}{_legend_html(color, mapping)}</div>'
    return mount


def _attrs_fingerprint(gdf: Any, cols: list[str]) -> int:
    """A cheap content fingerprint of the attribute columns (no per-geometry hashing) so the
    registry token is stable for identical data + distinct for different — keeps the tile
    source worker-local without paying a full GeoJSON content hash."""
    if not cols:
        return 0
    import pandas as pd

    return int(pd.util.hash_pandas_object(gdf[cols], index=False).sum() & 0xFFFFFFFFFFFFFFFF)


def to_geo(data: Any, *, geometry: str = "geometry", crs: Any = 4326) -> Any:
    """Turn a frame with a geometry column into a GeoPandas ``GeoDataFrame``.

    The bridge from :func:`spatial_sql` (which returns Polars) to :func:`geo_map`. The
    ``geometry`` column may be **WKB** bytes (a DuckDB ``GEOMETRY`` / ``ST_AsWKB`` column —
    the usual ``spatial_sql`` output), **WKT** text (``ST_AsText``), or shapely objects.
    Accepts a Polars or pandas frame; ``crs`` defaults to EPSG:4326 (lon/lat)::

        frame = gis.spatial_sql("SELECT name, ST_AsWKB(geom) AS geometry FROM p …", p=places)
        gdf = gis.to_geo(frame, geometry="geometry")

    Requires ``pip install "golit[gis]"``."""
    import geopandas as gpd
    import shapely

    pdf = data.to_pandas() if isinstance(data, pl.DataFrame) else data.copy()
    column = pdf[geometry]
    sample = next((v for v in column if v is not None), None)
    if isinstance(sample, (bytes, bytearray)):
        geom = shapely.from_wkb(list(column))
    elif isinstance(sample, str):
        geom = shapely.from_wkt(list(column))
    else:
        geom = list(column)  # already shapely geometries (or all-null)
    return gpd.GeoDataFrame(pdf.drop(columns=[geometry]), geometry=list(geom), crs=crs)


def _tooltip_fields(gdf: Any, tooltip: Any) -> list[str] | None:
    if tooltip is None or tooltip is False:
        return None
    if tooltip is True:
        geom = gdf.geometry.name
        return [c for c in gdf.columns if c != geom]
    if isinstance(tooltip, str):
        return [tooltip]
    return list(tooltip)


def explore(gdf: Any, **kwargs: Any) -> str:
    """The folium/leafmap escape hatch: delegate to ``gdf.explore(**kwargs)`` and embed
    its HTML. Returns a self-contained (iframe) folium map wrapped in a sized container,
    so it swaps cleanly like any other fragment — the cost is folium's client runtime,
    versus :func:`geo_map`'s native MapLibre. Use this when you want the folium ecosystem
    (layer control, marker clusters, plugins)::

        @app.view
        def map(regions):
            return gis.explore(regions, column="revenue", cmap="Blues")

    Requires ``pip install "golit[gis]"`` (folium ships with the extra)."""
    fmap = gdf.explore(**kwargs)
    inner = fmap._repr_html_()
    return (
        '<div class="golit-chart bg-surface-container-lowest rounded-xl overflow-hidden '
        f'shadow-sm">{inner}</div>'
    )


def spatial_sql(query: str, **frames: Any) -> pl.DataFrame:
    """Run a DuckDB **spatial** SQL ``query`` (``ST_*`` functions) over named frames,
    returning Polars — the spatial extension is loaded on the connection first, then the
    query runs through the ordinary :func:`golit.sql` path, so the result memoizes and
    feeds :func:`geo_map` like any frame::

        @app.reactive
        def nearby(places, radius_km=slider(1, 50, default=10)):
            return gis.spatial_sql(
                "SELECT name, geom FROM p "
                f"WHERE ST_DWithin(geom, ST_Point(-0.19, 5.6), {radius_km} / 111.0)",
                p=places,
            )

    Requires the ``sql`` extra (``pip install "golit[sql]"``); DuckDB downloads the
    spatial extension on first use. Select geometry as ``ST_AsWKB(geom)`` (or
    ``ST_AsText``) and pass it through :func:`to_geo` to feed :func:`geo_map`."""
    import warnings

    from .data import load_extension, sql

    load_extension("spatial")
    with warnings.catch_warnings():
        # A DuckDB GEOMETRY column comes back as a geoarrow.wkb extension type Polars
        # doesn't register; it loads fine as its Binary storage, so quiet the notice.
        warnings.filterwarnings("ignore", message=".*geoarrow.wkb.*")
        return sql(query, **frames)


def is_dataarray(value: Any) -> bool:
    """Whether ``value`` is an xarray ``DataArray`` — by class, without importing xarray.
    Used by :func:`golit.rendering.render_value` so a view can return a (georeferenced)
    raster directly."""
    cls = type(value)
    return cls.__name__ == "DataArray" and (cls.__module__ or "").startswith("xarray")


def _build_lut(anchors: list[str]) -> Any:
    """A 256-entry RGB lookup table from anchor hex colors (linearly interpolated)."""
    import numpy as np

    cols = np.array([[int(h[i : i + 2], 16) for i in (1, 3, 5)] for h in anchors], dtype=float)
    src = np.linspace(0.0, 1.0, len(cols))
    dst = np.linspace(0.0, 1.0, 256)
    lut = np.stack([np.interp(dst, src, cols[:, c]) for c in range(3)], axis=1)
    return lut.round().astype(np.uint8)  # (256, 3)


def _colormap_to_rgba(arr: Any, cmap: str, vmin: float | None, vmax: float | None) -> Any:
    """Colormap a 2-D float array to an ``(h, w, 4)`` uint8 RGBA array; non-finite cells
    (NaN nodata) become transparent. Returns the array and the (lo, hi) range used."""
    import numpy as np

    anchors = _RASTER_CMAPS.get(cmap)
    if anchors is None:
        raise ValueError(f"unknown cmap {cmap!r}; use one of {sorted(_RASTER_CMAPS)}")
    arr = np.asarray(arr, dtype=float)
    finite = np.isfinite(arr)
    lo = float(np.nanmin(arr)) if vmin is None else float(vmin)
    hi = float(np.nanmax(arr)) if vmax is None else float(vmax)
    if hi <= lo:
        hi = lo + 1.0
    norm = np.clip((np.where(finite, arr, lo) - lo) / (hi - lo), 0.0, 1.0)
    rgb = _build_lut(anchors)[(norm * 255).astype(np.uint8)]  # (h, w, 3)
    alpha = np.where(finite, 255, 0).astype(np.uint8)[..., None]
    return np.concatenate([rgb, alpha], axis=2), (lo, hi)


def _png_data_uri(rgba: Any) -> str:
    """Encode an ``(h, w, 4)`` uint8 RGBA array as a base64 PNG ``data:`` URI — a minimal
    dependency-free encoder (one IDAT, no row filtering), enough for a map image layer."""
    import base64
    import struct
    import zlib

    import numpy as np

    rgba = np.ascontiguousarray(rgba, dtype=np.uint8)
    height, width = rgba.shape[:2]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    rows = np.empty((height, width * 4 + 1), dtype=np.uint8)
    rows[:, 0] = 0  # filter type 0 (none) per scanline
    rows[:, 1:] = rgba.reshape(height, width * 4)
    idat = zlib.compress(rows.tobytes(), 9)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _load_raster(data: Any, bounds: Any, max_size: int) -> Any:
    """Resolve ``data`` (a rioxarray/xarray ``DataArray``, a GeoTIFF path, or a NumPy
    array + ``bounds``) to a north-up float array and its lon/lat bounds. The array keeps
    all bands — 2-D for a single band, band-first 3-D ``(band, y, x)`` for a multiband
    raster. Band selection / single-band validation is left to the caller (:func:`raster`
    takes one band; :func:`rgb` takes three)."""
    import numpy as np

    if isinstance(data, (str, os.PathLike)):
        import rioxarray

        data = rioxarray.open_rasterio(data)

    if is_dataarray(data):
        try:
            import rioxarray  # noqa: F401  (registers the .rio accessor on DataArray)
        except ModuleNotFoundError:
            pass
        da = data
        rio = getattr(da, "rio", None)
        crs = getattr(rio, "crs", None) if rio is not None else None
        if bounds is not None:
            minx, miny, maxx, maxy = (float(v) for v in bounds)
        elif crs is not None:
            if crs.to_epsg() != 4326:
                da = da.rio.reproject("EPSG:4326")
            minx, miny, maxx, maxy = (float(v) for v in da.rio.bounds())
        else:
            raise ValueError("raster: a DataArray without a CRS needs explicit bounds=[w,s,e,n]")
        arr = np.asarray(da.values, dtype=float)
        ys = da["y"].values if "y" in getattr(da, "coords", {}) else None
        if ys is not None and len(ys) > 1 and ys[0] < ys[-1]:
            arr = arr[..., ::-1, :]  # flip so row 0 is the north edge
    else:
        arr = np.asarray(data, dtype=float)
        if bounds is None:
            raise ValueError("raster: a NumPy array needs explicit bounds=[w,s,e,n]")
        minx, miny, maxx, maxy = (float(v) for v in bounds)

    # Downsample on the spatial axes only (the last two), so a band-first cube is preserved.
    step = max(1, int(np.ceil(max(arr.shape[-2:]) / max_size)))
    if step > 1:
        arr = arr[..., ::step, ::step]  # downsample large rasters (wire + draw cost)
    return arr, (minx, miny, maxx, maxy)


def _select_bands(arr: Any, bands: Any) -> Any:
    """Pick three bands from a multiband raster as a ``(3, y, x)`` stack. Accepts the
    rioxarray/rasterio band-first ``(band, y, x)`` layout and the channel-last
    ``(y, x, band)`` layout (auto-detected); ``bands`` indexes the band axis."""
    import numpy as np

    if arr.ndim == 2:
        raise ValueError("rgb: expected a multiband raster (>= 3 bands), got a single 2-D band")
    if arr.ndim != 3:
        raise ValueError(f"rgb: expected a 3-D (band, y, x) raster, got shape {arr.shape}")
    if arr.shape[-1] in (3, 4) and arr.shape[0] > 4:
        arr = np.moveaxis(arr, -1, 0)  # channel-last (y, x, band) -> band-first
    try:
        return np.stack([arr[b] for b in bands], axis=0)
    except IndexError as exc:
        raise ValueError(
            f"rgb: bands={tuple(bands)} out of range for a {arr.shape[0]}-band raster"
        ) from exc


def _composite_to_rgba(bands_arr: Any, percentiles: Any, vmin: Any, vmax: Any,
                       gamma: float | None) -> Any:
    """Stretch a ``(3, y, x)`` float array into an ``(h, w, 4)`` uint8 RGBA composite. Each
    band is contrast-stretched independently — to an explicit ``vmin``/``vmax`` (a scalar
    applied to all three, or a 3-sequence per band) or to the given ``percentiles`` —
    then optionally gamma-corrected. A pixel non-finite in any band is transparent (a
    nodata border). Returns the array and the per-band ``(lo, hi)`` ranges used."""
    import numpy as np

    plo, phi = percentiles
    height, width = bands_arr.shape[-2:]
    rgb_out = np.zeros((height, width, 3), dtype=np.uint8)
    finite_all = np.ones((height, width), dtype=bool)
    ranges: list[tuple[float, float]] = []
    for i in range(3):
        band = np.asarray(bands_arr[i], dtype=float)
        finite = np.isfinite(band)
        finite_all &= finite
        if vmin is not None and vmax is not None:
            lo = float(vmin[i]) if isinstance(vmin, (list, tuple)) else float(vmin)
            hi = float(vmax[i]) if isinstance(vmax, (list, tuple)) else float(vmax)
        elif finite.any():
            lo = float(np.nanpercentile(band, plo))
            hi = float(np.nanpercentile(band, phi))
        else:
            lo, hi = 0.0, 1.0  # an all-nodata band; the stretch is moot (alpha hides it)
        if hi <= lo:
            hi = lo + 1.0
        ranges.append((lo, hi))
        norm = np.clip((np.where(finite, band, lo) - lo) / (hi - lo), 0.0, 1.0)
        if gamma:
            norm = norm ** (1.0 / gamma)
        rgb_out[..., i] = (norm * 255).astype(np.uint8)
    alpha = np.where(finite_all, 255, 0).astype(np.uint8)[..., None]
    return np.concatenate([rgb_out, alpha], axis=2), ranges


def _image_layer_spec(
    url: str,
    bounds: tuple[float, float, float, float],
    *,
    opacity: float,
    basemap: Any,
    fit: bool,
    fit_padding: int,
    height: str,
    opts: dict[str, Any],
) -> str:
    """Place a PNG ``data:`` URI as a MapLibre image layer over ``basemap`` and return the
    map mount. Shared by :func:`raster` (colormapped single band) and :func:`rgb` (RGB
    composite); rides the same baked-vs-overlay basemap split as :func:`geo_map`."""
    minx, miny, maxx, maxy = bounds
    source = {
        "type": "image",
        "url": url,
        # MapLibre image coordinates: top-left, top-right, bottom-right, bottom-left.
        "coordinates": [[minx, maxy], [maxx, maxy], [maxx, miny], [minx, miny]],
    }
    layer = {"id": _RASTER, "type": "raster", "source": _RASTER,
             "paint": {"raster-opacity": opacity}}

    base = _base_style(basemap)
    spec: dict[str, Any] = {"height": height}
    if isinstance(base, str):
        spec["style"] = base
        spec["overlay"] = {"sources": {_RASTER: source}, "layers": [layer]}
    else:
        base["sources"][_RASTER] = source
        base["layers"].append(layer)
        spec["style"] = base

    if fit and "bounds" not in opts:
        spec["bounds"] = [[minx, miny], [maxx, maxy]]
        if fit_padding != 24:
            spec["fitPadding"] = fit_padding

    spec.update(opts)
    return chart_spec("maplibre", spec)


def raster(
    data: Any,
    *,
    cmap: str = "viridis",
    opacity: float = 0.85,
    band: int | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    bounds: Any = None,
    label: str = "value",
    basemap: Any = "default",
    fit: bool = True,
    fit_padding: int = 24,
    legend: bool = True,
    max_size: int = 1024,
    height: str = "420px",
    **opts: Any,
) -> str:
    """Render a georeferenced raster as a native MapLibre image layer (GIS phase 2).

    ``data`` is a rioxarray/xarray ``DataArray`` (reprojected to EPSG:4326 via its ``.rio``
    CRS), a **GeoTIFF path**, or a NumPy 2-D array with explicit ``bounds=[w, s, e, n]``. A
    single band is colormapped (``cmap``: ``"viridis"``, ``"magma"``, ``"blues"``,
    ``"terrain"``, ``"greys"``; ``vmin``/``vmax`` set the range, NaN nodata is transparent),
    encoded to a PNG, and placed as an image source on the ``basemap`` with ``opacity``. A
    colorbar ``legend`` (titled ``label``) is overlaid. Large rasters are downsampled to
    ``max_size`` px on the long edge to keep the fragment small::

        @app.view
        def map(elevation, cmap=select(["viridis", "terrain"], default="terrain")):
            return gis.raster(elevation, cmap=cmap, label="Elevation (m)")

    A view may also just ``return`` a georeferenced ``DataArray``. For a multiband raster
    (satellite imagery), see :func:`rgb`. Requires ``pip install "golit[gis-raster]"``."""
    arr, bnds = _load_raster(data, bounds, max_size)
    if arr.ndim == 3:
        arr = arr[0 if band is None else band]  # one band -> colormap; rgb() takes three
    if arr.ndim != 2:
        raise ValueError(f"raster: expected a 2-D band, got shape {arr.shape}")
    rgba, (lo, hi) = _colormap_to_rgba(arr, cmap, vmin, vmax)
    mount = _image_layer_spec(
        _png_data_uri(rgba), bnds, opacity=opacity, basemap=basemap,
        fit=fit, fit_padding=fit_padding, height=height, opts=opts,
    )
    if legend:
        mapping = {"kind": "numeric", "vmin": lo, "vmax": hi, "colors": _RASTER_CMAPS[cmap]}
        return f'<div class="golit-map-wrap relative">{mount}{_legend_html(label, mapping)}</div>'
    return mount


def rgb(
    data: Any,
    *,
    bands: Any = (0, 1, 2),
    percentiles: Any = (2.0, 98.0),
    vmin: Any = None,
    vmax: Any = None,
    gamma: float | None = None,
    opacity: float = 1.0,
    bounds: Any = None,
    basemap: Any = "default",
    fit: bool = True,
    fit_padding: int = 24,
    max_size: int = 1024,
    height: str = "420px",
    **opts: Any,
) -> str:
    """Render a multiband raster as a true/false-color **RGB composite** (GIS phase 2.5).

    ``data`` is a rioxarray/xarray ``DataArray`` (reprojected to EPSG:4326 via its ``.rio``
    CRS), a multiband **GeoTIFF path**, or a NumPy array with explicit ``bounds=[w, s, e, n]``
    — band-first ``(band, y, x)`` (the rasterio/rioxarray layout) or channel-last
    ``(y, x, band)`` (auto-detected). ``bands`` selects the three bands mapped to red,
    green, blue: the default ``(0, 1, 2)`` is a natural-color composite for an R-G-B raster;
    pick others for false color (e.g. NIR-R-G to highlight vegetation).

    Each band is contrast-stretched independently — by default to its 2nd–98th
    ``percentiles`` (robust to outliers), or to an explicit ``vmin``/``vmax`` (a scalar for
    all three, or a 3-sequence per band). ``gamma`` brightens (>1) or darkens (<1) the
    midtones; pixels that are nodata (non-finite) in any band are transparent. The composite
    is encoded to a PNG and placed as an image layer on the ``basemap`` with ``opacity``.
    Large rasters are downsampled to ``max_size`` px on the long edge::

        @app.view
        def scene(stack, combo=select(["natural", "false-color"], default="natural")):
            bands = (0, 1, 2) if combo == "natural" else (3, 0, 1)  # NIR-R-G
            return gis.rgb(stack, bands=bands)

    Requires ``pip install "golit[gis-raster]"``."""
    arr, bnds = _load_raster(data, bounds, max_size)
    composite = _select_bands(arr, bands)
    rgba, _ranges = _composite_to_rgba(composite, percentiles, vmin, vmax, gamma)
    return _image_layer_spec(
        _png_data_uri(rgba), bnds, opacity=opacity, basemap=basemap,
        fit=fit, fit_padding=fit_padding, height=height, opts=opts,
    )


def _tile_token(*parts: Any) -> str:
    """A short opaque token keying a tile source in the server registry — a hash of the
    path + render params, so re-rendering the same view reuses one registry slot."""
    import hashlib

    return hashlib.sha1(repr(parts).encode()).hexdigest()[:16]


def tiles(
    source: Any,
    *,
    bands: Any = None,
    cmap: str = "viridis",
    rescale: Any = None,
    opacity: float = 1.0,
    basemap: Any = "default",
    fit: bool = True,
    fit_padding: int = 24,
    min_zoom: int | None = None,
    max_zoom: int | None = None,
    tile_size: int = 256,
    height: str = "420px",
    **opts: Any,
) -> str:
    """Stream a **very large** raster as on-demand map tiles (GIS phase 2.5).

    Where :func:`raster`/:func:`rgb` ship the whole array as one PNG, ``tiles`` serves a
    **Cloud-Optimized GeoTIFF** (a local path or a remote ``http(s)`` URL) through a
    server-side tile route: rio-tiler reads only the ``z/x/y`` window each MapLibre request
    needs, colormaps/rescales it, and returns a 256-px PNG. A multi-gigabyte COG renders
    without ever loading or transmitting the full raster.

    ``bands`` selects the source band(s): omit (or one index) for a single band, colormapped
    with ``cmap`` (any rio-tiler colormap — ``"viridis"``, ``"magma"``, ``"terrain"``, …);
    three indexes for an RGB composite (no colormap). Each band is contrast-stretched to
    ``rescale`` — a ``(min, max)`` per band, or auto from the COG's 2nd–98th percentile
    statistics when omitted. The data's geographic footprint frames the camera (``fit``)::

        @app.view
        def scene(layer=select(["elevation", "landcover"], default="elevation")):
            return gis.tiles(f"/data/{layer}.tif", cmap="terrain")   # a COG path or URL

    Reading the source's metadata needs ``pip install "golit[gis-tiles]"`` (rio-tiler). The
    tile route is part of every Golit server; tiles for a session are served by the worker
    that rendered the view (the usual session affinity)."""
    from rasterio.crs import CRS
    from rio_tiler.colormap import cmap as _cmaps
    from rio_tiler.io import Reader

    from .server.tiles import register_source

    path = os.fspath(source) if isinstance(source, os.PathLike) else str(source)
    indexes = tuple(int(b) for b in bands) if bands is not None else (1,)
    is_rgb = len(indexes) >= 3
    cmap_name = None if is_rgb else cmap
    if cmap_name is not None and cmap_name not in _cmaps.list():
        raise ValueError(f"unknown cmap {cmap_name!r}; see rio_tiler.colormap.cmap.list()")

    with Reader(path) as src:
        west, south, east, north = src.get_geographic_bounds(CRS.from_epsg(4326))
        lo_zoom = src.minzoom if min_zoom is None else min_zoom
        hi_zoom = src.maxzoom if max_zoom is None else max_zoom
        if rescale is None:
            stats = src.statistics(indexes=indexes)
            rescale = [[float(b.percentile_2), float(b.percentile_98)] for b in stats.values()]
        elif rescale and not isinstance(rescale[0], (list, tuple)):
            rescale = [list(rescale)]  # a single (min, max) -> one band

    token = _tile_token(path, indexes, cmap_name, rescale)
    register_source(token, {"path": path, "indexes": indexes, "cmap": cmap_name,
                            "rescale": rescale})

    raster_source = {
        "type": "raster",
        "tiles": [f"/gis/tiles/{token}/{{z}}/{{x}}/{{y}}"],
        "tileSize": tile_size,
        "minzoom": lo_zoom,
        "maxzoom": hi_zoom,
        "bounds": [west, south, east, north],
    }
    layer = {"id": _RASTER, "type": "raster", "source": _RASTER,
             "paint": {"raster-opacity": opacity}}

    base = _base_style(basemap)
    spec: dict[str, Any] = {"height": height}
    if isinstance(base, str):
        spec["style"] = base
        spec["overlay"] = {"sources": {_RASTER: raster_source}, "layers": [layer]}
    else:
        base["sources"][_RASTER] = raster_source
        base["layers"].append(layer)
        spec["style"] = base

    if fit and "bounds" not in opts:
        spec["bounds"] = [[west, south], [east, north]]
        if fit_padding != 24:
            spec["fitPadding"] = fit_padding

    spec.update(opts)
    return chart_spec("maplibre", spec)


# Curated WhiteboxTools terrain operations: alias -> (tool method name, default params).
# `op` may also be any other WhiteboxTools tool name, with params passed straight through.
_TERRAIN_TOOLS: dict[str, tuple[str, dict[str, Any]]] = {
    "hillshade": ("hillshade", {"azimuth": 315.0, "altitude": 30.0}),
    "slope": ("slope", {"units": "degrees"}),
    "aspect": ("aspect", {}),
    "fill": ("fill_depressions", {}),
    "flow_accumulation": ("d8_flow_accumulation", {"out_type": "cells"}),
}

_WBT: Any = None


def _wbt() -> Any:
    """A process-cached WhiteboxTools runner (downloads its binary on first use)."""
    global _WBT
    if _WBT is None:
        import whitebox

        _WBT = whitebox.WhiteboxTools()
        _WBT.set_verbose_mode(False)
    return _WBT


def _materialize_dem(dem: Any, tmp: str, crs: Any) -> str:
    """Resolve ``dem`` to a GeoTIFF path WhiteboxTools can read: a path is used as-is; a
    georeferenced ``DataArray`` is written to a temp GeoTIFF (needs a CRS, which carries the
    transform/cell size terrain analysis depends on)."""
    if isinstance(dem, (str, os.PathLike)):
        return os.fspath(dem)
    if is_dataarray(dem):
        import rioxarray  # noqa: F401  (registers .rio)

        da = dem.rio.write_crs(crs) if crs is not None else dem
        if getattr(da.rio, "crs", None) is None:
            raise ValueError(
                "terrain: a DataArray DEM needs a CRS — set it with .rio.write_crs(...) "
                "or pass crs=. Terrain works in projected metres (e.g. a UTM CRS)."
            )
        path = os.path.join(tmp, "dem.tif")
        da.rio.to_raster(path)
        return path
    raise TypeError("terrain: dem must be a GeoTIFF path or a georeferenced DataArray")


def terrain(dem: Any, op: str = "hillshade", *, crs: Any = None, **params: Any) -> Any:
    """Run a **WhiteboxTools** terrain analysis on a DEM, returning the result as a
    georeferenced ``DataArray`` — feed it to :func:`raster`/:func:`tiles`, or just return it.

    ``dem`` is a DEM as a **GeoTIFF path** or a georeferenced rioxarray/xarray ``DataArray``
    (terrain analysis needs the cell size, so a bare NumPy array won't do; use a **projected**
    CRS in metres — e.g. a UTM zone — for meaningful slopes). ``op`` is one of the curated
    operations — ``"hillshade"``, ``"slope"``, ``"aspect"``, ``"fill"`` (fill depressions),
    ``"flow_accumulation"`` — or any other WhiteboxTools tool name; extra keyword args pass
    straight to the tool (e.g. ``azimuth=``/``altitude=`` for hillshade)::

        @app.reactive
        def shaded(dem, azimuth=slider(0, 360, default=315)):
            return gis.terrain(dem, "hillshade", azimuth=azimuth)   # -> a DataArray

        @app.view
        def relief(shaded):
            return gis.raster(shaded, cmap="greys", label="Hillshade")

    The DEM is run through the WhiteboxTools binary (downloaded once on first use) in a temp
    workspace, and the output is read back into memory. Requires
    ``pip install "golit[gis-terrain]"``."""
    import shutil
    import tempfile

    tool, defaults = _TERRAIN_TOOLS.get(op, (op, {}))
    merged = {**defaults, **params}
    tmp = tempfile.mkdtemp(prefix="golit_wbt_")
    try:
        dem_path = _materialize_dem(dem, tmp, crs)  # validates CRS before touching the binary
        out_path = os.path.join(tmp, f"{op}.tif")
        method = getattr(_wbt(), tool, None)
        if method is None or not callable(method):
            raise ValueError(
                f"unknown WhiteboxTools tool {op!r}; curated: {sorted(_TERRAIN_TOOLS)}, "
                "or any tool name from the WhiteboxTools manual"
            )
        rc = method(dem_path, out_path, **merged)
        if rc != 0 or not os.path.exists(out_path):
            raise RuntimeError(f"WhiteboxTools {tool} failed (return code {rc})")

        import rioxarray

        # open_rasterio on a single GeoTIFF returns a DataArray (its type is a broad union).
        with rioxarray.open_rasterio(out_path, masked=True) as src:  # type: ignore[union-attr]
            result = src.squeeze(drop=True).load()  # read fully so the temp file can be removed
            result_crs = src.rio.crs
        return result.rio.write_crs(result_crs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _ee_tile_url(map_id: Any) -> str:
    """Pull the ``{z}/{x}/{y}`` XYZ tile-URL template out of an Earth Engine ``getMapId()``
    result. Modern earthengine-api returns a ``tile_fetcher`` with a ``url_format``; very old
    versions only a ``mapid`` (+ optional ``token``), handled as a fallback."""
    getter = map_id.get if hasattr(map_id, "get") else lambda k, d=None: getattr(map_id, k, d)
    fetcher = getter("tile_fetcher")
    url = getattr(fetcher, "url_format", None)
    if url:
        return str(url)
    mapid = getter("mapid")
    if not mapid:
        raise ValueError("ee_layer: getMapId() returned no tile_fetcher or mapid")
    token = getter("token") or ""
    url = f"https://earthengine.googleapis.com/map/{mapid}/{{z}}/{{x}}/{{y}}"
    return url + (f"?token={token}" if token else "")


def ee_layer(
    image: Any,
    *,
    vis: Any = None,
    opacity: float = 1.0,
    basemap: Any = "default",
    center: Any = None,
    zoom: float | None = None,
    attribution: str = "Map data © Google Earth Engine",
    height: str = "420px",
    **opts: Any,
) -> str:
    """Overlay a **Google Earth Engine** image as live XYZ tiles (GIS phase 3).

    ``image`` is anything with a ``getMapId(vis)`` method — an ``ee.Image`` (reduce a
    collection first with ``.median()``/``.mosaic()``). Earth Engine renders the tiles on its
    own servers; this asks for a tile-URL template (``image.getMapId(vis)``) and points a
    MapLibre **raster source** at it, overlaid on ``basemap``. ``vis`` is the usual Earth
    Engine visualization dict (``{"min", "max", "bands"}`` or ``"palette"``); ``center`` /
    ``zoom`` frame the camera (an EE image can be global, so there's no data extent to fit)::

        import ee
        ee.Initialize(project="my-cloud-project")        # after `earthengine authenticate`

        @app.view
        def scene(cloud=slider(5, 80, default=30)):
            s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                  .filterBounds(aoi)
                  .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud))
                  .median())
            return gis.ee_layer(s2, vis={"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000},
                                center=[-0.15, 5.62], zoom=10)

    This function imports nothing itself — Earth Engine authentication and the ``ee`` objects
    are the caller's. Install the client with ``pip install "golit[gis-ee]"`` and authenticate
    once (``earthengine authenticate`` + ``ee.Initialize(project=…)``)."""
    map_id = image.getMapId(vis or {})
    source = {
        "type": "raster",
        "tiles": [_ee_tile_url(map_id)],
        "tileSize": 256,
        "attribution": attribution,
    }
    layer = {"id": _RASTER, "type": "raster", "source": _RASTER,
             "paint": {"raster-opacity": opacity}}

    base = _base_style(basemap)
    spec: dict[str, Any] = {"height": height}
    if isinstance(base, str):
        spec["style"] = base
        spec["overlay"] = {"sources": {_RASTER: source}, "layers": [layer]}
    else:
        base["sources"][_RASTER] = source
        base["layers"].append(layer)
        spec["style"] = base

    if center is not None:
        spec["center"] = list(center)
    if zoom is not None:
        spec["zoom"] = zoom

    spec.update(opts)
    return chart_spec("maplibre", spec)
