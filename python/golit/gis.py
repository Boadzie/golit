"""GIS — reactive maps as ordinary Golit views.

A map is a view like any other: return one from an ``@app.view`` node and a control
that touches its inputs rebuilds *only* that view. Phase 1 covers vector data and
native MapLibre GL rendering plus DuckDB spatial SQL:

* :func:`maplibre` — a native, GPU vector map from a style (URL or dict) and a camera;
* :func:`geo_map` — a GeoDataFrame straight to a MapLibre choropleth/line/point map
  (a view may also just *return* the GeoDataFrame — see :func:`golit.rendering.render_value`);
* :func:`explore` — the folium/leafmap escape hatch (``gdf.explore`` embedded as-is);
* :func:`spatial_sql` — DuckDB ``ST_*`` SQL over Polars/GeoJSON sources, returning Polars.

Everything heavy (GeoPandas, pyproj, folium, DuckDB) is imported lazily *inside* the
functions, so ``import golit`` — and therefore ``import golit.gis`` — never pulls them
in. Install the extra with ``pip install "golit[gis]"`` (DuckDB spatial rides on the
existing ``sql`` extra).
"""

from __future__ import annotations

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

# Raster basemap presets — all key-free. A dict basemap is used as a full style;
# "none" draws just a flat background so the data carries the map.
_CARTO_ATTR = "© OpenStreetMap, © CARTO"
_CARTO_LIGHT = "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"
_CARTO_DARK = "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
_BASEMAPS = {
    "default": (_CARTO_LIGHT, _CARTO_ATTR),
    "light": (_CARTO_LIGHT, _CARTO_ATTR),
    "positron": (_CARTO_LIGHT, _CARTO_ATTR),
    "dark": (_CARTO_DARK, _CARTO_ATTR),
    "osm": ("https://tile.openstreetmap.org/{z}/{x}/{y}.png", "© OpenStreetMap contributors"),
}

_SOURCE = "golit-geo"  # the GeoJSON source/layer id geo_map injects into the style


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


def _base_style(basemap: Any) -> dict[str, Any]:
    """Build the base MapLibre style (just the basemap) that geo_map layers onto."""
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
    try:
        tiles, attribution = _BASEMAPS[basemap]
    except KeyError:
        raise ValueError(
            f"unknown basemap {basemap!r}; use one of {sorted(_BASEMAPS)}, 'none', or a style dict"
        ) from None
    source = {"type": "raster", "tiles": [tiles], "tileSize": 256, "attribution": attribution}
    return {
        "version": 8,
        "sources": {"basemap": source},
        "layers": [{"id": "basemap", "type": "raster", "source": "basemap"}],
    }


def _color_expr(gdf: Any, column: str) -> Any:
    """A MapLibre paint expression mapping ``column`` to a color: an ``interpolate``
    ramp for a numeric column, a ``match`` over distinct values for a categorical one."""
    from pandas.api.types import is_numeric_dtype

    series = gdf[column]
    if is_numeric_dtype(series):
        vmin = float(series.min())
        vmax = float(series.max())
        if vmin == vmax:
            vmax = vmin + 1.0
        stops: list[Any] = []
        last = len(_SEQUENTIAL) - 1
        for i, color in enumerate(_SEQUENTIAL):
            stops.extend([vmin + (vmax - vmin) * i / last, color])
        return ["interpolate", ["linear"], ["get", column], *stops]
    cats = list(dict.fromkeys(str(v) for v in series.tolist()))
    match: list[Any] = ["match", ["get", column]]
    for i, cat in enumerate(cats):
        match.extend([cat, _CATEGORICAL[i % len(_CATEGORICAL)]])
    match.append("#9ca3af")  # fallback for values not seen at build time
    return match


def _data_layers(gdf: Any, color: str | None) -> list[dict[str, Any]]:
    """The fill/line/circle layer(s) for the GeoJSON source, chosen by geometry type."""
    kinds = {str(t).replace("Multi", "") for t in gdf.geom_type.dropna().unique()}
    if "Polygon" in kinds:
        fill = color and _color_expr(gdf, color) or "#1565c0"
        return [
            {
                "id": _SOURCE,
                "type": "fill",
                "source": _SOURCE,
                "paint": {"fill-color": fill, "fill-opacity": 0.7},
            },
            {
                "id": f"{_SOURCE}-outline",
                "type": "line",
                "source": _SOURCE,
                "paint": {"line-color": "#ffffff", "line-width": 0.6},
            },
        ]
    if "LineString" in kinds:
        line = color and _color_expr(gdf, color) or "#1565c0"
        return [
            {
                "id": _SOURCE,
                "type": "line",
                "source": _SOURCE,
                "paint": {"line-color": line, "line-width": 2.5},
            }
        ]
    circle = color and _color_expr(gdf, color) or "#1565c0"
    return [
        {
            "id": _SOURCE,
            "type": "circle",
            "source": _SOURCE,
            "paint": {
                "circle-color": circle,
                "circle-radius": 5,
                "circle-stroke-color": "#ffffff",
                "circle-stroke-width": 1,
            },
        }
    ]


def geo_map(
    gdf: Any,
    *,
    color: str | None = None,
    tooltip: Any = None,
    basemap: Any = "default",
    fit: bool = True,
    height: str = "420px",
    **opts: Any,
) -> str:
    """Render a GeoPandas ``GeoDataFrame`` as a native MapLibre map.

    The frame is reprojected to EPSG:4326 if needed, serialized to GeoJSON, and added to
    a MapLibre style as a source with a fill (polygons), line (lines), or circle (points)
    layer picked from the geometry type. ``color`` names a column to drive the fill — a
    blue ramp for a numeric column (a choropleth), a categorical palette for a text one.
    ``tooltip`` shows feature properties on click: ``True`` for every attribute, or a
    column name / list of names. ``basemap`` is a preset (``"default"``, ``"light"``,
    ``"dark"``, ``"osm"``, ``"none"``) or a full style ``dict``. With ``fit`` the camera
    frames the data's bounds::

        @app.view
        def map(regions):                  # regions is a filtered GeoDataFrame
            return gis.geo_map(regions, color="revenue", tooltip=["name", "revenue"])

    A view may also just ``return`` the GeoDataFrame — :func:`golit.rendering.render_value`
    routes it here with defaults. Requires ``pip install "golit[gis]"``."""
    import json

    crs = getattr(gdf, "crs", None)
    if crs is not None and crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    geojson = json.loads(gdf.to_json())
    style = _base_style(basemap)
    style["sources"][_SOURCE] = {"type": "geojson", "data": geojson}
    style["layers"].extend(_data_layers(gdf, color))

    spec: dict[str, Any] = {"style": style, "height": height}
    if fit and "bounds" not in opts:
        minx, miny, maxx, maxy = (float(v) for v in gdf.total_bounds)
        spec["bounds"] = [[minx, miny], [maxx, maxy]]

    fields = _tooltip_fields(gdf, tooltip)
    if fields:
        spec["tooltip"] = fields
        spec["tooltipLayer"] = _SOURCE

    spec.update(opts)
    return chart_spec("maplibre", spec)


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
    spatial extension on first use."""
    from .data import load_extension, sql

    load_extension("spatial")
    return sql(query, **frames)
