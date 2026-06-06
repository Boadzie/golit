"""Face detection — a *real* OpenCV detector over the visitor's own webcam.

Where `browser_camera` uses a dependency-light brightness tracker as a stand-in, this runs an
actual model: OpenCV's bundled Haar-cascade face detector. It's the same shape any detector
takes — `@app.on_frame` receives an `(H, W, 3)` uint8 RGB array, draws on it, and returns it —
so swapping in YOLO, MediaPipe, or your own network is a matter of changing the body.

The cascade ships **inside OpenCV** (`cv2.data.haarcascades`), so there's no model to download.
Camera access needs a **secure context**: `localhost` (where `golit run` serves) or `https`.

    pip install "golit[vision-cv]"
    golit run examples/face_detect/app.py
"""

from __future__ import annotations

import cv2
import golit.ui as ui
import numpy as np
from golit import App, create_app

app = App(title="Face Detection")

# Load the bundled frontal-face cascade once, at import — detectMultiScale is then cheap to call.
_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
_ACCENT = (86, 220, 140)  # RGB — the frame arrives RGB, so we draw in RGB


@app.on_frame("faces")
def detect(frame: np.ndarray) -> np.ndarray:
    """Find faces and box each one. Runs in a worker thread (sync handler), so the model
    never stalls the event loop; one frame is in flight at a time, so a slow detect just
    lowers the rate. Returns the annotated RGB array for the browser to paint."""
    out = frame.copy()  # decoded arrays are read-only; cv2 draws in place, needs writable
    gray = cv2.cvtColor(out, cv2.COLOR_RGB2GRAY)
    gray = cv2.equalizeHist(gray)  # even out lighting so detection is steadier
    faces = _CASCADE.detectMultiScale(
        gray, scaleFactor=1.2, minNeighbors=5, minSize=(60, 60)
    )
    for x, y, w, h in faces:
        cv2.rectangle(out, (x, y), (x + w, y + h), _ACCENT, 2)
        cv2.rectangle(out, (x, y - 18), (x + 54, y), _ACCENT, -1)
        cv2.putText(out, "face", (x + 4, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (8, 24, 14), 1)
    label = f"{len(faces)} face{'s' if len(faces) != 1 else ''}"
    cv2.putText(out, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 232, 240), 2)
    return out


@app.view
def live() -> str:
    return ui.card(
        ui.camera("faces", title="Your camera", height=360, width=640),
        ui.caption("Each frame runs through OpenCV's Haar-cascade face detector, server-side."),
        title="Face detection",
        subtitle="getUserMedia → WebSocket → @app.on_frame (OpenCV) → back",
    )


application = create_app(app)
