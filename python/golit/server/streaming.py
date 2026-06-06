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

By default the producer runs **once per viewer** (each request is its own generator) — right
for synthetic feeds and a per-session camera. For a single shared device watched by many,
``@app.stream(name, shared=True)`` runs the producer **once** behind a :class:`_StreamHub` that
fans the latest frame out to every viewer; the producer starts on the first viewer and its
``finally`` runs when the last one leaves.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import anyio
from litestar import Request, get
from litestar.exceptions import NotFoundException
from litestar.params import FromPath
from litestar.response import Stream

_log = logging.getLogger("golit.stream")

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
    """Drive a producer (called fresh per request) into a stream of MJPEG parts.

    A producer that raises (a camera read fails, a model errors) ends the stream
    gracefully — logged, not crashed — so one bad frame closes the response cleanly
    instead of bubbling a 500 mid-stream. Client disconnects (``GeneratorExit`` /
    ``CancelledError``) are not ``Exception`` and propagate untouched, so cleanup still runs."""
    try:
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
    except Exception:
        _log.exception("stream producer failed; ending the feed")


def _pull_jpeg(iterator: Any) -> Any:
    """Pull + encode the next frame of a sync producer in a worker thread (no multipart
    wrapping — the hub stores raw JPEG and wraps per viewer). Sentinel at end."""
    frame = next(iterator, _SENTINEL)
    return _SENTINEL if frame is _SENTINEL else _to_jpeg(frame)


def _close_sync(frames: Any) -> None:
    """Close a finished sync generator so its ``finally`` (camera release) runs."""
    close = getattr(frames, "close", None)
    if close is not None:
        close()


class _StreamHub:
    """One producer run fanned out to many viewers of a ``shared=True`` stream.

    The producer starts on the first :meth:`subscribe` and is pulled by a single background
    task that keeps the *latest* JPEG; every viewer waits for the next frame and yields it
    (slow viewers simply drop intermediate frames — it's MJPEG, latest wins). When the last
    viewer leaves, the loop stops and the producer's ``finally`` runs, releasing the device;
    a later viewer restarts it. One hub lives per stream name in ``app.state.stream_hubs``.
    """

    def __init__(self, produce: Any) -> None:
        self._produce = produce
        self._latest: bytes | None = None
        self._ready = asyncio.Event()  # replaced each frame; the old one is set to wake waiters
        self._done = False  # producer has stopped — wake viewers so they end too
        self._viewers = 0
        self._task: asyncio.Task[None] | None = None

    def _publish(self, jpeg: bytes) -> None:
        self._latest = jpeg
        ready, self._ready = self._ready, asyncio.Event()
        ready.set()

    async def _drive(self) -> None:
        frames: Any = None
        try:
            frames = self._produce()
            if hasattr(frames, "__anext__"):  # an async generator/iterator
                async for frame in frames:
                    if self._viewers == 0:
                        break
                    self._publish(await anyio.to_thread.run_sync(_to_jpeg, frame))
            else:
                iterator = iter(frames)
                while self._viewers > 0:
                    jpeg = await anyio.to_thread.run_sync(_pull_jpeg, iterator)
                    if jpeg is _SENTINEL:
                        break
                    self._publish(jpeg)
        except Exception:
            # A failed producer/encode ends the shared feed cleanly (viewers see _done and
            # exit) rather than dying as an unretrieved task exception. A later viewer restarts.
            _log.exception("shared stream producer failed; ending the feed")
        finally:
            if frames is not None:
                aclose = getattr(frames, "aclose", None)
                if aclose is not None:
                    await aclose()
                else:
                    await anyio.to_thread.run_sync(_close_sync, frames)
            self._latest = None
            self._done = True
            self._ready.set()  # release any viewer waiting on the next frame

    def _ensure_running(self) -> None:
        if self._task is None or self._task.done():
            self._done = False
            self._ready = asyncio.Event()
            self._task = asyncio.ensure_future(self._drive())

    async def subscribe(self) -> AsyncIterator[bytes]:
        """Yield the latest JPEG as each new frame lands, for one viewer's lifetime —
        ending when the producer stops (its frames run out or the last viewer leaves)."""
        self._viewers += 1
        self._ensure_running()
        try:
            while True:
                ready = self._ready
                await ready.wait()
                if self._latest is not None:
                    yield self._latest
                if self._done:
                    return
        finally:
            self._viewers -= 1


async def _hub_mjpeg(hub: _StreamHub) -> AsyncIterator[bytes]:
    """Wrap a hub subscription's raw JPEG frames as MJPEG parts."""
    async for jpeg in hub.subscribe():
        yield _part(jpeg)


@get("/golit/stream/{name:str}")
async def stream(name: FromPath[str], request: Request) -> Stream:
    """Serve the MJPEG stream registered as ``name`` with ``@app.stream``; 404 if unknown.
    A ``shared=True`` stream is fanned out from one :class:`_StreamHub`; otherwise each
    request drives its own producer."""
    producers: dict[str, Any] = getattr(request.app.state, "streams", {})
    produce = producers.get(name)
    if produce is None:
        raise NotFoundException(f"no such stream: {name!r}")
    shared: Any = getattr(request.app.state, "shared_streams", frozenset())
    if name in shared:
        hubs: dict[str, _StreamHub] = request.app.state.stream_hubs
        body = _hub_mjpeg(hubs.setdefault(name, _StreamHub(produce)))
    else:
        body = _mjpeg(produce)
    return Stream(
        body,
        media_type=_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
