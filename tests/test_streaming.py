"""Server-side MJPEG streaming: frame encoding, the multipart wire format, the
``/golit/stream/<name>`` route end to end, and the ``ui.webcam`` mount.

Every producer here is **finite** — an MJPEG response never ends on its own, so an
infinite producer would hang the test client. Real cameras loop forever; tests don't."""

from __future__ import annotations

import asyncio
import time

import golit.ui as ui
from golit import App, create_app
from golit.server.streaming import _mjpeg, _part, _StreamHub, _to_jpeg
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


async def test_mjpeg_ends_cleanly_when_producer_raises_mid_stream():
    def produce():
        yield b"\xff\xd8one\xff\xd9"
        raise RuntimeError("camera died")  # must not bubble out of the stream

    body = await _collect(produce)
    assert body.count(b"--golitframe") == 1  # the good frame, then a clean end


async def test_mjpeg_ends_cleanly_when_producer_raises_immediately():
    def produce():
        raise RuntimeError("no camera")

    assert await _collect(produce) == b""  # no frames, no exception


# -- the shared-source hub ----------------------------------------------------


async def _take(hub: _StreamHub, k: int) -> list[bytes]:
    """Pull ``k`` frames from one hub viewer, then close the subscription cleanly."""
    gen = hub.subscribe()
    out: list[bytes] = []
    try:
        async for jpeg in gen:
            out.append(jpeg)
            if len(out) >= k:
                break
    finally:
        await gen.aclose()
    return out


async def test_shared_hub_runs_one_producer_for_many_viewers():
    runs = 0

    def produce():
        nonlocal runs
        runs += 1
        n = 0
        while True:
            n += 1
            time.sleep(0.005)
            yield b"\xff\xd8" + str(n).encode() + b"\xff\xd9"

    hub = _StreamHub(produce)
    a, b = await asyncio.gather(_take(hub, 3), _take(hub, 3))
    if hub._task is not None:
        await asyncio.wait_for(hub._task, 2)  # let it notice viewers==0 and stop
    assert runs == 1  # one producer for both viewers, not one each
    assert len(a) == 3 and len(b) == 3


async def test_shared_hub_releases_producer_when_last_viewer_leaves():
    released = False

    def produce():
        nonlocal released
        try:
            while True:
                time.sleep(0.005)
                yield b"\xff\xd8f\xff\xd9"
        finally:
            released = True

    hub = _StreamHub(produce)
    got = await _take(hub, 1)
    if hub._task is not None:
        await asyncio.wait_for(hub._task, 2)
    assert got and released is True  # finally ran -> a real camera handle would be freed


async def test_shared_hub_survives_producer_error():
    def produce():
        yield b"\xff\xd8one\xff\xd9"
        raise RuntimeError("camera died")

    hub = _StreamHub(produce)
    got = await asyncio.wait_for(_take(hub, 5), 2)  # asks 5; producer makes 1 then errors
    assert got == [b"\xff\xd8one\xff\xd9"]  # the good frame, then the viewer ends cleanly
    if hub._task is not None:
        await asyncio.wait_for(hub._task, 2)  # drive task finished (error was caught, not raised)


async def test_shared_hub_ends_viewers_when_producer_stops():
    def produce():
        for _ in range(2):
            yield b"\xff\xd8x\xff\xd9"

    hub = _StreamHub(produce)
    # asks for more frames than the producer makes — the subscription must still finish
    got = await asyncio.wait_for(_take(hub, 99), 2)
    assert got == [b"\xff\xd8x\xff\xd9", b"\xff\xd8x\xff\xd9"]


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


def test_shared_route_serves_mjpeg_from_the_hub():
    app = App(title="Shared")

    @app.stream("shared_cam", shared=True)
    def shared_cam():
        for _ in range(3):
            yield b"\xff\xd8frame\xff\xd9"

    @app.view
    def live() -> str:
        return ui.webcam("shared_cam")

    with TestClient(app=create_app(app)) as client:
        resp = client.get("/golit/stream/shared_cam")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("multipart/x-mixed-replace")
    assert resp.content.count(b"--golitframe") == 3


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
