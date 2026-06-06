"""Browser-microphone clip handling — the audio mirror of :mod:`golit.server.processing`.

``@app.on_audio(name)`` registers a handler; the WebSocket route ``/golit/audio/{name}``
receives a 16-bit PCM **WAV** clip the visitor recorded (captured with the Web Audio API in
the browser), passes the bytes to the handler, and sends the result back: a rendered HTML
fragment to display, or audio ``bytes`` to play. Decoding is the handler's job — WAV needs only
Python's stdlib ``wave``, no ffmpeg.

Sync handlers — and a heavy transcribe — run in a worker thread (``anyio.to_thread``) so they
never stall the event loop; async handlers are awaited. A handler (or render) that raises on one
clip is logged and a small notice is sent back, keeping the recorder usable instead of dropping
the socket.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

import anyio
from litestar import WebSocket, websocket
from litestar.exceptions import WebSocketDisconnect
from litestar.params import FromPath

from ..rendering import render_value

_log = logging.getLogger("golit.audio")

_UNKNOWN_RECORDER = 4404  # private WS close code: no handler registered for this name
_ERROR_HTML = (
    '<div class="golit-recorder-error text-error text-sm">Could not process the recording.</div>'
)


async def _run_audio(handler: Any, wav: bytes) -> Any:
    """Run the clip handler off the event loop when it's sync; await it when it's async."""
    if inspect.iscoroutinefunction(handler):
        return await handler(wav)
    return await anyio.to_thread.run_sync(handler, wav)


@websocket("/golit/audio/{name:str}")
async def audio(socket: WebSocket, name: FromPath[str]) -> None:
    """Handle clips for the recorder registered as ``name`` via ``@app.on_audio``. Each
    inbound binary message is one WAV clip; the reply is text (rendered HTML to show) or
    binary (audio to play). Closes with code 4404 if no such handler; ends on disconnect."""
    await socket.accept()
    handlers: dict[str, Any] = getattr(socket.app.state, "audio_handlers", {})
    handler = handlers.get(name)
    if handler is None:
        await socket.close(code=_UNKNOWN_RECORDER)
        return
    try:
        while True:
            wav = await socket.receive_bytes()
            try:
                result = await _run_audio(handler, wav)
                audio_out = isinstance(result, (bytes, bytearray))
                payload: Any = bytes(result) if audio_out else render_value(result)
            except Exception:
                _log.exception("audio handler %r failed", name)
                await socket.send_text(_ERROR_HTML)
                continue
            if audio_out:
                await socket.send_bytes(payload)  # audio to play back
            else:
                await socket.send_text(payload)  # HTML fragment to display
    except WebSocketDisconnect:
        pass
