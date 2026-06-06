"""Browser-mic recorder: the sync/async clip runner, the binary ``/golit/audio/<name>``
WebSocket route (HTML result vs audio playback vs error notice), and the ``ui.recorder`` mount."""

from __future__ import annotations

import io
import wave

import golit.ui as ui
import numpy as np
import pytest
from golit import App, create_app
from golit.server.audio import _run_audio
from litestar.testing import TestClient


def _wav(seconds: float = 0.2, rate: int = 16000, freq: int = 440, amp: float = 0.5) -> bytes:
    n = int(rate * seconds)
    pcm = (amp * np.sin(2 * np.pi * freq * np.arange(n) / rate) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


# -- the clip runner ----------------------------------------------------------


async def test_run_audio_sync_handler():
    def handler(wav: bytes) -> str:
        return f"<p>{len(wav)} bytes</p>"

    assert await _run_audio(handler, b"abc") == "<p>3 bytes</p>"


async def test_run_audio_async_handler():
    async def handler(wav: bytes) -> str:
        return "<p>ok</p>"

    assert await _run_audio(handler, b"x") == "<p>ok</p>"


# -- the live route -----------------------------------------------------------


def build_audio_app(handler=None):
    app = App(title="Rec")
    app.on_audio("note")(handler or (lambda wav: f"<p>{len(wav)}</p>"))

    @app.view
    def live() -> str:
        return ui.recorder("note", title="Voice")

    return create_app(app)


def test_route_returns_rendered_html():
    with TestClient(app=build_audio_app()) as client:
        with client.websocket_connect("/golit/audio/note") as ws:
            wav = _wav()
            ws.send_bytes(wav)
            result = ws.receive_text()
    assert f"<p>{len(wav)}</p>" in result  # the handler's HTML came back as a text message


def test_handler_returning_bytes_plays_back():
    raw = b"RIFFfake-audio-bytes"

    with TestClient(app=build_audio_app(lambda wav: raw)) as client:
        with client.websocket_connect("/golit/audio/note") as ws:
            ws.send_bytes(_wav())
            back = ws.receive_bytes()
    assert back == raw  # bytes return -> sent back as binary for playback


def test_unknown_recorder_is_closed_with_4404():
    from litestar.exceptions import WebSocketDisconnect

    with TestClient(app=build_audio_app()) as client:
        with client.websocket_connect("/golit/audio/nope") as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_bytes()
    assert exc.value.code == 4404


def test_handler_error_sends_notice_and_keeps_socket():
    def boom(wav: bytes):
        raise RuntimeError("transcribe service down")

    with TestClient(app=build_audio_app(boom)) as client:
        with client.websocket_connect("/golit/audio/note") as ws:
            ws.send_bytes(_wav())
            notice = ws.receive_text()
            ws.send_bytes(_wav())  # socket still alive — a second clip also gets a reply
            notice2 = ws.receive_text()
    assert "Could not process" in notice and "Could not process" in notice2


# -- the recorder mount -------------------------------------------------------


def test_page_mounts_recorder_and_bootstrap():
    with TestClient(app=build_audio_app()) as client:
        body = client.get("/").text
    assert 'data-golit-recorder="note"' in body
    assert "golit-recorder-btn" in body
    assert "initRecorder" in body  # the RECORDER_BOOTSTRAP shipped


def test_recorder_markup_escapes_and_carries_config():
    html = ui.recorder("note", title="<x>", max_seconds=20, hint="be brief <b>")
    assert 'data-golit-recorder="note"' in html
    assert 'data-max-seconds="20"' in html
    assert "<x>" not in html and "&lt;x&gt;" in html
    assert "&lt;b&gt;" in html


def test_recorder_playback_and_download_default_on():
    html = ui.recorder("note")
    assert 'data-playback="1"' in html  # local playback of your own clip
    assert "golit-recorder-download" in html and 'download="recording.wav"' in html
    assert "golit-recorder-audio" in html  # the inline player


def test_recorder_playback_and_download_can_be_off():
    html = ui.recorder("note", playback=False, download=False)
    assert 'data-playback="0"' in html
    assert "golit-recorder-download" not in html
    assert "golit-recorder-audio" in html  # player stays (handler may still return audio)
