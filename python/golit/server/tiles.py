"""Server-side raster tiling for very large rasters (GIS phase 2.5).

:func:`golit.gis.tiles` registers a Cloud-Optimized GeoTIFF (a local path or a remote
``http(s)`` URL) under an opaque token and emits a MapLibre **raster source** pointing at
this route. The route reads each ``z/x/y`` tile on demand with rio-tiler, colormaps or
rescales it, and returns a PNG. Only the small per-tile window crosses the wire, so a
multi-gigabyte COG renders without ever shipping the whole array — the same selective
principle as the rest of Golit, applied to pixels instead of nodes.

The ``token -> source`` registry is process-local and bounded (LRU). Serving a tile needs
the worker that registered the token, so tiles rely on the same **session affinity** as
everything else in Golit (the worker that rendered the view serves its tiles). The token
is an opaque hash, never a path — the registry is the allowlist, so a tile request can only
reach a source a view has already opened. rio-tiler is imported lazily *inside* the route,
so importing ``golit`` (and registering this handler) never pulls it in.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from litestar import Response, get
from litestar.params import FromPath

# token -> {"path", "indexes", "cmap", "rescale"}; bounded so a long-lived server that has
# rendered many distinct tile sources doesn't grow without limit (LRU by access).
_REGISTRY: OrderedDict[str, dict[str, Any]] = OrderedDict()
_LOCK = threading.Lock()
_MAX_SOURCES = 256


def register_source(token: str, entry: dict[str, Any]) -> None:
    """Register (or refresh) a tile source under ``token``, evicting the least-recently
    used entry past the cap. Called by :func:`golit.gis.tiles` at render time."""
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


def _render_tile(entry: dict[str, Any], x: int, y: int, z: int) -> bytes:
    """Read one web-mercator tile from the registered source and render it to PNG bytes:
    rescale the selected band(s) to 0–255 and (for a single band) apply the colormap."""
    from rio_tiler.colormap import cmap as cmaps
    from rio_tiler.io import Reader

    with Reader(entry["path"]) as src:
        img = src.tile(x, y, z, indexes=entry["indexes"])
    rescale = entry.get("rescale")
    if rescale:
        img.rescale(in_range=rescale)
    colormap = cmaps.get(entry["cmap"]) if entry.get("cmap") else None
    return img.render(img_format="PNG", colormap=colormap)


@get("/gis/tiles/{token:str}/{z:int}/{x:int}/{y:int}", sync_to_thread=True)
def tile(
    token: FromPath[str], z: FromPath[int], x: FromPath[int], y: FromPath[int]
) -> Response:
    """Serve a single ``z/x/y`` PNG tile for a registered source. Unknown tokens and tiles
    outside the source's footprint return 404 (MapLibre simply skips a missing tile)."""
    entry = _lookup(token)
    if entry is None:
        return Response(b"", media_type="image/png", status_code=404)
    from rio_tiler.errors import TileOutsideBounds

    try:
        png = _render_tile(entry, x, y, z)
    except TileOutsideBounds:
        return Response(b"", media_type="image/png", status_code=404)
    return Response(
        png, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"}
    )
