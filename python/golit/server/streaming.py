"""Server-side MJPEG video streaming for webcam / computer-vision views.

``@app.stream(name)`` registers a frame producer; the ``GET /golit/stream/{name}`` route
runs it and pushes frames as a multipart **MJPEG** (``multipart/x-mixed-replace``) response,
which :func:`golit.ui.webcam` shows in a plain ``<img>`` (no client JS). A producer yields
JPEG ``bytes`` (e.g. ``cv2.imencode``) or ``(H, W, 3)`` uint8 RGB arrays — arrays are encoded
to JPEG with Pillow (the ``vision`` extra), imported lazily so importing golit never needs it.

Sync producers are pulled (and arrays encoded) in a worker thread via ``anyio.to_thread``, so
a blocking camera read or a CV model never stalls the event loop; async producers are awaited
directly. The producer's ``try/finally`` runs when the client disconnects and the generator is
closed, so a camera handle is released.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import anyio
from litestar import Request, get
from litestar.exceptions import NotFoundException
from litestar.params import FromPath
from litestar.response import Stream

_BOUNDARY = "golitframe"
_MEDIA_TYPE = f"multipart/x-mixed-replace; boundary={_BOUNDARY}"
_SENTINEL: Any = object()


def _to_jpeg(frame: Any) -> bytes:
    """A frame -> JPEG bytes. ``bytes`` pass through (already encoded); an array-like
    ``(H, W, 3)`` uint8 RGB frame is encoded with Pillow (the ``vision`` extra)."""
    if isinstance(frame, (bytes, bytearray)):
        return bytes(frame)
    import io

    import numpy as np
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(np.asarray(frame).astype("uint8")).save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def _part(jpeg: bytes) -> bytes:
    """Wrap one JPEG frame as a multipart/x-mixed-replace part."""
    return (
        b"--" + _BOUNDARY.encode() + b"\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
    )


def _next_jpeg(iterator: Any) -> Any:
    """Pull the next frame from a sync iterator and encode it — run in a worker thread so
    a blocking read / CPU-bound encode stays off the event loop. Returns the sentinel at end."""
    frame = next(iterator, _SENTINEL)
    return _SENTINEL if frame is _SENTINEL else _part(_to_jpeg(frame))


async def _mjpeg(produce: Any) -> AsyncIterator[bytes]:
    """Drive a producer (called fresh per request) into a stream of MJPEG parts."""
    frames = produce()
    if hasattr(frames, "__anext__"):  # an async generator/iterator
        async for frame in frames:
            yield _part(_to_jpeg(frame))
        return
    iterator = iter(frames)
    while True:
        part = await anyio.to_thread.run_sync(_next_jpeg, iterator)
        if part is _SENTINEL:
            break
        yield part


@get("/golit/stream/{name:str}")
async def stream(name: FromPath[str], request: Request) -> Stream:
    """Serve the MJPEG stream registered as ``name`` with ``@app.stream``; 404 if unknown."""
    producers: dict[str, Any] = getattr(request.app.state, "streams", {})
    produce = producers.get(name)
    if produce is None:
        raise NotFoundException(f"no such stream: {name!r}")
    return Stream(
        _mjpeg(produce),
        media_type=_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
