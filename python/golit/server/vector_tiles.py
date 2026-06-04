"""Server-side vector tiling for large GeoDataFrames (GIS phase 2.5).

:func:`golit.gis.vector_tiles` registers a (Web-Mercator-reprojected) GeoDataFrame under an
opaque token and emits a MapLibre **vector source**. This route encodes the features falling
in each ``z/x/y`` tile to a Mapbox Vector Tile (MVT) on demand, so a GeoDataFrame with
hundreds of thousands of features renders without ever serializing the whole GeoJSON to the
client — the vector analog of :mod:`golit.server.tiles` (which does the same for rasters).

The ``token -> GeoDataFrame`` registry is process-local and bounded (LRU); the data stays
worker-local (only the per-tile MVT crosses the wire), so tiles rely on the same session
affinity as everything else, and the token is an opaque hash, never a path. mapbox-vector-tile
and shapely are imported lazily inside the route, so importing ``golit`` never pulls them in.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from litestar import Response, get
from litestar.params import FromPath

# Half the Web-Mercator (EPSG:3857) world extent in metres — the WebMercatorQuad origin.
_WORLD = 20037508.342789244

# token -> {"gdf" (EPSG:3857 GeoDataFrame), "properties", "layer"}; bounded LRU by access.
_REGISTRY: OrderedDict[str, dict[str, Any]] = OrderedDict()
_LOCK = threading.Lock()
_MAX_SOURCES = 128


def register_source(token: str, entry: dict[str, Any]) -> None:
    """Register (or refresh) a vector tile source under ``token``, evicting the
    least-recently used entry past the cap. Called by :func:`golit.gis.vector_tiles`."""
    with _LOCK:
        _REGISTRY[token] = entry
        _REGISTRY.move_to_end(token)
        while len(_REGISTRY) > _MAX_SOURCES:
            _REGISTRY.popitem(last=False)


def _lookup(token: str) -> dict[str, Any] | None:
    with _LOCK:
        entry = _REGISTRY.get(token)
        if entry is not None:
            _REGISTRY.move_to_end(token)
        return entry


def _tile_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """The EPSG:3857 ``(left, bottom, right, top)`` bounds of a WebMercatorQuad tile —
    the standard XYZ scheme, computed inline (matches morecantile's ``xy_bounds``)."""
    span = 2 * _WORLD / (2**z)
    left = -_WORLD + x * span
    top = _WORLD - y * span
    return left, top - span, left + span, top


def _native(value: Any) -> Any:
    """Coerce a GeoDataFrame cell to an MVT-encodable scalar (numpy types -> Python)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:  # noqa: BLE001 - fall through to a string
            pass
    return str(value)


def _encode_tile(entry: dict[str, Any], z: int, x: int, y: int) -> bytes | None:
    """Encode the features intersecting tile ``z/x/y`` as MVT bytes, or ``None`` if the tile
    is empty. Features are clipped to the (slightly buffered) tile so coordinates and tile
    size stay bounded; the exact tile bounds quantize geometry into the 0–4096 MVT grid."""
    import mapbox_vector_tile as mvt
    from shapely.geometry import box

    left, bottom, right, top = _tile_bounds_3857(z, x, y)
    buf = (right - left) * 0.05  # a small margin so polygon/line edges aren't cut at the seam
    gdf = entry["gdf"]
    subset = gdf.cx[left - buf : right + buf, bottom - buf : top + buf]  # sindex bbox filter
    if subset.empty:
        return None

    clip = box(left - buf, bottom - buf, right + buf, top + buf)
    geoms = subset.geometry.intersection(clip).to_numpy()
    columns = entry["properties"]
    records = subset[columns].to_dict("records") if columns else [{}] * len(subset)
    features = [
        {"geometry": geom, "properties": {k: _native(v) for k, v in props.items()}}
        for geom, props in zip(geoms, records, strict=True)
        if geom is not None and not geom.is_empty
    ]
    if not features:
        return None
    return mvt.encode(
        [{"name": entry["layer"], "features": features}],
        default_options={
            "quantize_bounds": (left, bottom, right, top),
            "extents": 4096,
            "y_coord_down": False,
        },
    )


@get("/gis/vector/{token:str}/{z:int}/{x:int}/{y:int}", sync_to_thread=True)
def vector_tile(
    token: FromPath[str], z: FromPath[int], x: FromPath[int], y: FromPath[int]
) -> Response:
    """Serve one ``z/x/y`` MVT tile for a registered GeoDataFrame. Unknown tokens 404; an
    empty tile (no features) returns 204, which MapLibre treats as a blank tile."""
    entry = _lookup(token)
    if entry is None:
        return Response(b"", media_type="application/vnd.mapbox-vector-tile", status_code=404)
    pbf = _encode_tile(entry, z, x, y)
    if not pbf:
        return Response(b"", media_type="application/vnd.mapbox-vector-tile", status_code=204)
    return Response(
        pbf,
        media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": "public, max-age=3600"},
    )
