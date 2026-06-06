"""Browser-camera frame processing: JPEG decode/encode, the sync/async processor runner,
the binary ``/golit/camera/<name>`` WebSocket route end to end, and the ``ui.camera`` mount."""

from __future__ import annotations

import io

import golit.ui as ui
import numpy as np
import pytest
from golit import App, create_app
from golit.server.processing import _decode, _run
from golit.server.streaming import _to_jpeg
from litestar.testing import TestClient
from PIL import Image

_JPEG_SOI = b"\xff\xd8"


def _jpeg(h: int = 32, w: int = 48, fill: int = 30) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(np.full((h, w, 3), fill, "uint8")).save(buf, "JPEG")
    return buf.getvalue()


# -- decode / encode ----------------------------------------------------------


def test_decode_gives_rgb_array():
    arr = _decode(_jpeg(32, 48))
    assert arr.shape == (32, 48, 3)
    assert arr.dtype == np.uint8


def test_to_jpeg_decode_roundtrips():
    arr = _decode(_to_jpeg(np.full((16, 16, 3), 200, "uint8")))
    assert arr.shape == (16, 16, 3)
    assert abs(int(arr.mean()) - 200) < 4  # JPEG is lossy, but close


# -- the processor runner -----------------------------------------------------


async def test_run_with_sync_handler():
    def handler(frame):
        out = frame.copy()
        out[:8, :, :] = (255, 0, 0)  # red strip on top
        return out

    arr = _decode(await _run(handler, _jpeg(40, 40)))
    assert int(arr[:8, :, 0].mean()) > 200  # red strip survived the round trip


async def test_run_with_async_handler():
    async def handler(frame):
        return frame  # passthrough

    out = await _run(handler, _jpeg(24, 24))
    assert out.startswith(_JPEG_SOI)


async def test_handler_may_return_jpeg_bytes():
    raw = _jpeg(24, 24)

    def handler(frame):
        return raw  # already-encoded bytes pass straight through

    assert await _run(handler, _jpeg(24, 24)) == raw


# -- the live route -----------------------------------------------------------


def build_camera_app():
    app = App(title="Cam")

    @app.on_frame("detector")
    def detect(frame):
        out = frame.copy()
        out[:8, :, :] = (0, 255, 0)  # green strip
        return out

    @app.view
    def live() -> str:
        return ui.camera("detector", title="Your camera")

    return create_app(app)


def test_route_processes_a_frame_and_sends_it_back():
    with TestClient(app=build_camera_app()) as client:
        with client.websocket_connect("/golit/camera/detector") as ws:
            ws.send_bytes(_jpeg(40, 40))
            result = ws.receive_bytes()
    arr = _decode(result)
    assert result.startswith(_JPEG_SOI)
    assert int(arr[:8, :, 1].mean()) > 200  # the handler's green strip came back


def test_unknown_camera_is_closed_with_4404():
    from litestar.exceptions import WebSocketDisconnect

    with TestClient(app=build_camera_app()) as client:
        with client.websocket_connect("/golit/camera/nope") as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_bytes()
    assert exc.value.code == 4404


# -- the camera mount ---------------------------------------------------------


def test_page_mounts_camera_and_bootstrap():
    with TestClient(app=build_camera_app()) as client:
        body = client.get("/").text
    assert 'data-golit-camera="detector"' in body
    assert "golit-camera-out" in body and "golit-camera-src" in body
    assert "getUserMedia" in body  # the CAMERA_BOOTSTRAP shipped


def test_camera_bootstrap_handles_denied_access():
    from golit.rendering.html import CAMERA_BOOTSTRAP

    assert "cameraError" in CAMERA_BOOTSTRAP  # rejections mapped to plain language
    assert "NotAllowedError" in CAMERA_BOOTSTRAP  # permission denied
    assert "NotReadableError" in CAMERA_BOOTSTRAP  # camera busy
    assert "secure page" in CAMERA_BOOTSTRAP  # insecure-context notice, not a stuck spinner


def test_camera_markup_escapes_and_carries_config():
    html = ui.camera("cam", title="<x>", width=320, fps=10, quality=0.5)
    assert 'data-golit-camera="cam"' in html
    assert 'data-width="320"' in html and 'data-fps="10"' in html
    assert 'data-quality="0.5"' in html
    assert "<x>" not in html and "&lt;x&gt;" in html
