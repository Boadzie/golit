"""Browser Camera — process the visitor's *own* webcam, server-side (the inbound mirror of
`webcam_stream`, which produces frames on the server).

`golit.ui.camera(name)` grabs the camera with `getUserMedia` and streams JPEG frames up over a
WebSocket; the `@app.on_frame(name)` handler runs on each one and the annotated frame it returns
is painted back — one frame in flight at a time, so a slow handler just lowers the rate.

The handler here needs only the `vision` extra (Pillow + numpy), no OpenCV: it finds the
brightest region of the frame (a crude "look here" tracker — point a lamp or your face at the
camera and watch the box follow) and draws a labelled box plus a frame counter on it. Swap the
body for your own detector — it receives an `(H, W, 3)` uint8 RGB array and returns one.

Camera access needs a **secure context**: `localhost` (where `golit run` serves) or `https`.

    pip install "golit[vision]"
    golit run examples/browser_camera/app.py
"""

from __future__ import annotations

import golit.ui as ui
import numpy as np
from golit import App, create_app
from PIL import Image, ImageDraw

app = App(title="Browser Camera")

_GRID = 6  # luminance is pooled into a _GRID x _GRID map to locate the brightest cell
_state = {"n": 0}


def _brightest_cell(rgb: np.ndarray) -> tuple[int, int, float]:
    """Pool luminance into a coarse grid and return the (row, col) of the brightest cell
    and its strength in 0–1. Cheap, dependency-light, and visibly tracks a light source."""
    lum = rgb @ np.array([0.299, 0.587, 0.114])
    pooled = np.array(
        [[cell.mean() for cell in np.array_split(strip, _GRID, axis=1)]
         for strip in np.array_split(lum, _GRID, axis=0)]
    )
    row, col = divmod(int(pooled.argmax()), _GRID)
    return row, col, float(pooled.max() / 255.0)


@app.on_frame("tracker")
def tracker(frame: np.ndarray) -> np.ndarray:
    _state["n"] += 1
    img = Image.fromarray(frame)
    draw = ImageDraw.Draw(img)
    h, w, _ = frame.shape

    row, col, strength = _brightest_cell(frame)
    cw, ch = w / _GRID, h / _GRID
    x0, y0 = int(col * cw), int(row * ch)
    x1, y1 = int(x0 + cw), int(y0 + ch)
    accent = (86, 220, 140)
    draw.rectangle([x0, y0, x1, y1], outline=accent, width=3)
    draw.rectangle([x0, y0 - 16, x0 + 96, y0], fill=accent)
    draw.text((x0 + 4, y0 - 14), f"bright {strength:.2f}", fill=(8, 24, 14))
    draw.text((8, 8), f"frame {_state['n']} · {w}x{h}", fill=(230, 232, 240))
    return np.asarray(img)


@app.view
def live() -> str:
    return ui.card(
        ui.camera("tracker", title="Your camera", height=360, width=640),
        ui.caption("Frames go to the server, get a box drawn on the brightest region, come back."),
        title="Browser camera → server CV",
        subtitle="getUserMedia → WebSocket → @app.on_frame → back",
    )


application = create_app(app)
