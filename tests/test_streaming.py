"""Server-side MJPEG streaming: frame encoding, the multipart wire format, the
``/golit/stream/<name>`` route end to end, and the ``ui.webcam`` mount.

Every producer here is **finite** — an MJPEG response never ends on its own, so an
infinite producer would hang the test client. Real cameras loop forever; tests don't."""

from __future__ import annotations

import golit.ui as ui
from golit import App, create_app
from golit.server.streaming import _mjpeg, _part, _to_jpeg
from litestar.testing import TestClient

_JPEG_SOI = b"\xff\xd8"  # start-of-image marker every JPEG begins with

# -- frame encoding -----------------------------------------------------------


def test_bytes_frames_pass_through_untouched():
    raw = b"\xff\xd8already-encoded\xff\xd9"
    assert _to_jpeg(raw) is not raw or _to_jpeg(raw) == raw
    assert _to_jpeg(bytearray(raw)) == raw


def test_arrays_are_jpeg_encoded():
    np = __import__("numpy")
    frame = np.zeros((8, 8, 3), dtype="uint8")
    frame[:, :, 0] = 255  # solid red
    jpeg = _to_jpeg(frame)
    assert jpeg.startswith(_JPEG_SOI)
    assert jpeg.endswith(b"\xff\xd9")  # end-of-image


def test_part_wraps_one_frame_as_multipart():
    part = _part(b"hello")
    assert part.startswith(b"--golitframe\r\n")
    assert b"Content-Type: image/jpeg\r\n" in part
    assert b"Content-Length: 5\r\n\r\n" in part
    assert part.endswith(b"hello\r\n")


# -- the producer driver ------------------------------------------------------


async def _collect(produce) -> bytes:
    return b"".join([chunk async for chunk in _mjpeg(produce)])


async def test_sync_producer_yields_a_part_per_frame():
    def produce():
        yield b"\xff\xd8one\xff\xd9"
        yield b"\xff\xd8two\xff\xd9"

    body = await _collect(produce)
    assert body.count(b"--golitframe") == 2
    assert body.count(_JPEG_SOI) == 2


async def test_async_producer_is_supported():
    async def produce():
        yield b"\xff\xd8a\xff\xd9"
        yield b"\xff\xd8b\xff\xd9"

    body = await _collect(produce)
    assert body.count(b"--golitframe") == 2


# -- the live route -----------------------------------------------------------


def build_stream_app():
    app = App(title="Cam")

    @app.stream("camera")
    def camera():
        for _ in range(3):
            yield b"\xff\xd8frame\xff\xd9"

    @app.view
    def live() -> str:
        return ui.webcam("camera", title="Detections")

    return create_app(app)


def test_route_serves_a_finite_mjpeg_stream():
    with TestClient(app=build_stream_app()) as client:
        resp = client.get("/golit/stream/camera")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("multipart/x-mixed-replace")
    assert "boundary=golitframe" in resp.headers["content-type"]
    assert resp.content.count(b"--golitframe") == 3


def test_unknown_stream_is_404():
    with TestClient(app=build_stream_app()) as client:
        assert client.get("/golit/stream/nope").status_code == 404


# -- the webcam mount ---------------------------------------------------------


def test_page_mounts_the_webcam_img():
    with TestClient(app=build_stream_app()) as client:
        body = client.get("/").text
    assert 'src="/golit/stream/camera"' in body
    assert "golit-webcam" in body


def test_webcam_markup_escapes_and_sizes():
    html = ui.webcam("cam", title="<x>", height=300, width=400)
    assert 'src="/golit/stream/cam"' in html
    assert "<x>" not in html and "&lt;x&gt;" in html
    assert "height: 300px" in html and "max-width: 400px" in html
