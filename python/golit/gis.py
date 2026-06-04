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

_SOURCE = "golit-geo"  # the GeoJSON source/layer id geo_map injects into the style
_RASTER = "golit-raster"  # the image source/layer id raster() injects into the style

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


def _data_layers(gdf: Any, mapping: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The fill/line/circle layer(s) for the GeoJSON source, chosen by geometry type."""
    paint = mapping["expr"] if mapping else "#1565c0"
    kinds = {str(t).replace("Multi", "") for t in gdf.geom_type.dropna().unique()}
    if "Polygon" in kinds:
        return [
            {
                "id": _SOURCE,
                "type": "fill",
                "source": _SOURCE,
                "paint": {"fill-color": paint, "fill-opacity": 0.7},
            },
            {
                "id": f"{_SOURCE}-outline",
                "type": "line",
                "source": _SOURCE,
                "paint": {"line-color": "#ffffff", "line-width": 0.6},
            },
        ]
    if "LineString" in kinds:
        return [
            {
                "id": _SOURCE,
                "type": "line",
                "source": _SOURCE,
                "paint": {"line-color": paint, "line-width": 2.5},
            }
        ]
    return [
        {
            "id": _SOURCE,
            "type": "circle",
            "source": _SOURCE,
            "paint": {
                "circle-color": paint,
                "circle-radius": 5,
                "circle-stroke-color": "#ffffff",
                "circle-stroke-width": 1,
            },
        }
    ]


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


def _resolve_raster(data: Any, band: int | None, bounds: Any, max_size: int) -> Any:
    """Resolve ``data`` (a rioxarray/xarray ``DataArray``, a GeoTIFF path, or a NumPy
    array + ``bounds``) to a north-up 2-D float array and its lon/lat bounds."""
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

    if arr.ndim == 3:
        arr = arr[0 if band is None else band]
    if arr.ndim != 2:
        raise ValueError(f"raster: expected a 2-D band, got shape {arr.shape}")
    step = max(1, int(np.ceil(max(arr.shape) / max_size)))
    if step > 1:
        arr = arr[::step, ::step]  # downsample large rasters (wire + draw cost)
    return arr, (minx, miny, maxx, maxy)


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

    A view may also just ``return`` a georeferenced ``DataArray``. Requires
    ``pip install "golit[gis-raster]"``."""
    arr, (minx, miny, maxx, maxy) = _resolve_raster(data, band, bounds, max_size)
    rgba, (lo, hi) = _colormap_to_rgba(arr, cmap, vmin, vmax)
    source = {
        "type": "image",
        "url": _png_data_uri(rgba),
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
    mount = chart_spec("maplibre", spec)
    if legend:
        mapping = {"kind": "numeric", "vmin": lo, "vmax": hi, "colors": _RASTER_CMAPS[cmap]}
        return f'<div class="golit-map-wrap relative">{mount}{_legend_html(label, mapping)}</div>'
    return mount
