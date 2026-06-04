"""Webcam Stream — a live computer-vision view (server-side MJPEG).

`@app.stream(name)` registers a frame producer; `golit.ui.webcam(name)` shows it in a plain
`<img>` that the browser plays as MJPEG (`multipart/x-mixed-replace`) — no client JS, and the
stream is independent of the reactive graph, so the live view never re-renders mid-frame.

This demo needs no camera: the producer **synthesizes** frames — a box bouncing across the
canvas with a fake "person 0.98" detection drawn on each one, the same shape a real detector
would emit. To use an actual webcam, swap the body for an OpenCV capture loop (see `camera()`
below, left commented) and yield `cv2.imencode(".jpg", frame)[1].tobytes()` after drawing your
model's output on `frame`.

A producer yields either pre-encoded JPEG `bytes` or `(H, W, 3)` uint8 RGB arrays (encoded for
you with Pillow). Sync producers are pulled in a worker thread, so a blocking camera read or a
heavy model never stalls the event loop.

    pip install "golit[vision]"
    golit run examples/webcam_stream/app.py
"""

from __future__ import annotations

import time

import golit.ui as ui
import numpy as np
from golit import App, create_app
from PIL import Image, ImageDraw

app = App(title="Webcam Stream")

_W, _H, _FPS = 640, 360, 20
_BOX = 90  # detection box side, px


def _frame(t: int) -> np.ndarray:
    """One synthetic 'camera' frame: a dim gradient backdrop with a box bouncing across
    it, boxed and labelled like an object detector's output. `t` is the frame index."""
    img = Image.new("RGB", (_W, _H), (18, 18, 24))
    draw = ImageDraw.Draw(img)
    # a faint moving sweep so the backdrop is obviously live
    sweep = int((np.sin(t / 18) * 0.5 + 0.5) * _W)
    draw.line([(sweep, 0), (sweep, _H)], fill=(32, 34, 44), width=40)

    # bounce a box around (triangle wave on each axis)
    span_x, span_y = _W - _BOX, _H - _BOX
    x = int(abs((t * 7) % (2 * span_x) - span_x))
    y = int(abs((t * 4) % (2 * span_y) - span_y))
    conf = 0.90 + 0.09 * (np.sin(t / 9) * 0.5 + 0.5)

    draw.rectangle([x, y, x + _BOX, y + _BOX], outline=(86, 220, 140), width=3)
    draw.rectangle([x, y - 18, x + 86, y], fill=(86, 220, 140))
    draw.text((x + 4, y - 16), f"person {conf:.2f}", fill=(8, 24, 14))
    draw.text((10, 10), f"frame {t}", fill=(120, 124, 140))
    return np.asarray(img)


@app.stream("detector")
def detector():
    """Yield frames forever at ~`_FPS`. Golit closes the generator when the client
    disconnects, so a real implementation would release its camera in a `finally`."""
    t = 0
    period = 1.0 / _FPS
    while True:
        start = time.monotonic()
        yield _frame(t)
        t += 1
        time.sleep(max(0.0, period - (time.monotonic() - start)))


# --- swap the synthetic producer for a real webcam like this -----------------
# import cv2
#
# @app.stream("detector")
# def camera():
#     cap = cv2.VideoCapture(0)
#     try:
#         while True:
#             ok, frame = cap.read()
#             if not ok:
#                 break
#             # ... run your detector and draw boxes on `frame` (BGR) ...
#             yield cv2.imencode(".jpg", frame)[1].tobytes()
#     finally:
#         cap.release()


@app.view
def live() -> str:
    return ui.card(
        ui.webcam("detector", title="Live detection", height=360, width=640),
        ui.caption("Synthetic frames — no camera needed. Swap in an OpenCV loop for a real one."),
        title="Computer vision",
        subtitle="Server-side MJPEG over a single <img>",
    )


application = create_app(app)
