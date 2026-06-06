"""Audio Recorder — record a clip in the browser, analyze it server-side.

`golit.ui.recorder(name)` captures the visitor's microphone with the Web Audio API and uploads
the clip as 16-bit PCM **WAV** over a WebSocket; the `@app.on_audio(name)` handler runs on the
bytes and whatever it returns is shown back in the panel. The mic mirror of `browser_camera`.

This handler needs **no extra deps**: Python's stdlib `wave` decodes the clip and numpy (a core
Golit dependency) measures it — duration, peak/RMS level, and a little waveform. Swap the body
for a real model (Whisper, an STT API) and return the transcript; or return audio `bytes` to
play something back.

Mic access needs a **secure context**: `localhost` (where `golit run` serves) or `https`.

    pip install golit
    golit run examples/audio_recorder/app.py
"""

from __future__ import annotations

import io
import wave

import golit.ui as ui
import numpy as np
from golit import App, create_app

app = App(title="Audio Recorder")


def _read_wav(wav: bytes) -> tuple[np.ndarray, int]:
    """Decode 16-bit PCM WAV bytes to float samples in -1..1 and the sample rate (stdlib)."""
    with wave.open(io.BytesIO(wav), "rb") as w:
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return samples, rate


def _waveform_svg(samples: np.ndarray, buckets: int = 96, height: int = 56) -> str:
    """A peak-per-bucket bar waveform — a tiny dependency-free SVG."""
    if samples.size == 0:
        return ""
    step = max(1, samples.size // buckets)
    peaks = np.abs(samples[: step * buckets]).reshape(-1, step).max(axis=1)
    bars = []
    for i, p in enumerate(peaks):
        bh = max(1.0, float(p) * (height - 2))
        bars.append(
            f'<rect x="{i * 4}" y="{(height - bh) / 2:.1f}" width="3" '
            f'height="{bh:.1f}" rx="1.5" fill="currentColor"/>'
        )
    width = len(peaks) * 4
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'class="w-full text-primary" style="height:{height}px">{"".join(bars)}</svg>'
    )


def _dbfs(x: float) -> str:
    return "-∞" if x <= 1e-6 else f"{20 * np.log10(x):.0f}"


@app.on_audio("note")
def analyze(wav: bytes) -> str:
    """Measure the recorded clip and render a little report card."""
    samples, rate = _read_wav(wav)
    if samples.size == 0:
        return ui.alert("That clip was empty.", kind="warning")
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples**2)))
    return ui.card(
        _waveform_svg(samples),
        ui.grid(
            [
                ui.metric("Duration", f"{samples.size / rate:.1f}s"),
                ui.metric("Peak", f"{_dbfs(peak)} dBFS"),
                ui.metric("Loudness", f"{_dbfs(rms)} dBFS"),
            ],
            cols=3,
        ),
        title="Clip analysis",
    )


@app.view
def live() -> str:
    return ui.card(
        ui.recorder(
            "note",
            title="Record a clip",
            hint="Click to record, click to stop — it's analyzed server-side.",
            max_seconds=15,
        ),
        ui.caption("Captured as WAV in the browser, decoded with Python's stdlib `wave`."),
        title="Audio recorder → server analysis",
        subtitle="getUserMedia → WAV → WebSocket → @app.on_audio → result",
    )


application = create_app(app)
