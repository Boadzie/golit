"""Browser-camera frame processing for computer-vision views — the inbound mirror of
:mod:`golit.server.streaming` (which produces frames *on* the server).

``@app.on_frame(name)`` registers a per-frame processor; the WebSocket route
``/golit/camera/{name}`` receives JPEG frames captured from the visitor's own webcam
(``getUserMedia``), decodes each to an ``(H, W, 3)`` uint8 RGB array, runs the processor, and
sends the value it returns back as JPEG for :func:`golit.ui.camera` to display. Decode and
encode use Pillow (the ``vision`` extra), imported lazily so importing golit never needs it.

Sync processors — and every JPEG decode/encode — run in a worker thread (``anyio.to_thread``)
so a heavy model never stalls the event loop; async processors are awaited. The client keeps a
single frame in flight (it waits for each result before sending the next), so a slow processor
just lowers the frame rate rather than building an unbounded backlog.
"""

from __future__ import annotations

import inspect
from typing import Any

import anyio
from litestar import WebSocket, websocket
from litestar.exceptions import WebSocketDisconnect
from litestar.params import FromPath

from .streaming import _to_jpeg  # frame (array | bytes) -> JPEG bytes; reused as-is

_UNKNOWN_CAMERA = 4404  # private WS close code: no processor registered for this name


def _decode(jpeg: bytes) -> Any:
    """JPEG bytes -> an ``(H, W, 3)`` uint8 RGB array (Pillow; the ``vision`` extra)."""
    import io

    import numpy as np
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(jpeg)).convert("RGB"))


def _process_sync(handler: Any, jpeg: bytes) -> bytes:
    """Decode -> run a sync handler -> encode, all in one worker-thread hop."""
    return _to_jpeg(handler(_decode(jpeg)))


async def _run(handler: Any, jpeg: bytes) -> bytes:
    """Turn one inbound JPEG into one annotated JPEG, keeping CPU off the event loop.

    A sync handler does decode + run + encode in a single thread; an async handler is awaited
    on the loop while only the decode and encode are threaded."""
    if inspect.iscoroutinefunction(handler):
        frame = await anyio.to_thread.run_sync(_decode, jpeg)
        result = await handler(frame)
        return await anyio.to_thread.run_sync(_to_jpeg, result)
    return await anyio.to_thread.run_sync(_process_sync, handler, jpeg)


@websocket("/golit/camera/{name:str}")
async def camera(socket: WebSocket, name: FromPath[str]) -> None:
    """Process the visitor's webcam frames with the handler registered as ``name`` via
    ``@app.on_frame``. Receives a JPEG per message, sends the annotated JPEG back; closes with
    code 4404 if no such handler. Ends when the client disconnects."""
    await socket.accept()
    handlers: dict[str, Any] = getattr(socket.app.state, "frame_handlers", {})
    handler = handlers.get(name)
    if handler is None:
        await socket.close(code=_UNKNOWN_CAMERA)
        return
    try:
        while True:
            jpeg_in = await socket.receive_bytes()
            await socket.send_bytes(await _run(handler, jpeg_in))
    except WebSocketDisconnect:
        pass
