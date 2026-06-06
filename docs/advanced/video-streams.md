# Video streams (webcam / computer vision)

Some views aren't a fragment that re-renders on a change — they're a **continuous picture**: a camera feed, a detector drawing boxes on each frame, a synthetic visualization that animates on its own. Golit serves those as a **server-side MJPEG stream**: the server pushes a never-ending sequence of JPEG frames and the browser plays them in a plain `<img>`.

This stays on-brand with the rest of Golit — no client framework, no canvas glue, no JSON-to-pixels code. The browser plays `multipart/x-mixed-replace` natively, and the stream lives **outside** the reactive graph, so the live view holds one stable connection and never re-renders mid-frame.

Video flows **both directions**, and Golit covers each. Most of this page is *server → browser* — a feed produced on the server (`@app.stream` + `ui.webcam`). The mirror, *browser → server* — the visitor's own webcam streamed up for processing (`@app.on_frame` + `ui.camera`) — is [further down](#the-other-direction-the-visitors-own-camera).

## The two halves

A video view is a producer plus a component, mirroring the [`@app.on_message` / `ui.chat`](websockets.md) split for chat:

```python
import golit.ui as ui
from golit import App, create_app

app = App(title="Webcam Stream")


@app.stream("detector")          # ① the frame producer
def detector():
    while True:
        frame = ...              # an (H, W, 3) uint8 RGB array, or JPEG bytes
        yield frame


@app.view
def live() -> str:               # ② where it shows
    return ui.webcam("detector", title="Live detection")


application = create_app(app)
```

`@app.stream(name)` registers a producer under `name`; `ui.webcam(name)` renders an `<img>` pointed at `GET /golit/stream/<name>`. Run it with `golit run app.py` and the frames just play.

## Producers: what to `yield`

A producer is a generator (sync or `async`) that yields one frame at a time. A frame is either:

- **`(H, W, 3)` uint8 RGB array** — encoded to JPEG for you with Pillow (the `vision` extra), or
- **pre-encoded JPEG `bytes`** — e.g. `cv2.imencode(".jpg", frame)[1].tobytes()`, which needs no extra at all.

```python
import cv2

@app.stream("detector")
def camera():
    cap = cv2.VideoCapture(0)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            # ... run your model and draw boxes on `frame` (BGR) ...
            yield cv2.imencode(".jpg", frame)[1].tobytes()
    finally:
        cap.release()            # runs when the client disconnects
```

!!! note "Blocking reads stay off the event loop"
    A **sync** producer is pulled in a worker thread (`anyio.to_thread`), so a blocking `cap.read()` or a CPU-bound model never stalls the server. An **`async def` + `yield`** producer is awaited directly — use that when your frame source is already async (an `await`-able camera SDK, an async queue).

!!! warning "Clean up in `finally`"
    Each request starts a **fresh** call to your producer. When the client closes the tab, Golit closes the generator — your `finally:` runs, so that's where a camera handle, file, or device is released. Without it you leak the device on every reconnect.

## The component

```python
ui.webcam(name, *, title=None, height=384, width=None)
```

Renders a `golit-webcam` panel with an `<img src="/golit/stream/<name>">`. `height` is the display height in pixels; `width` (optional) caps the width, otherwise the frame scales to its container. The image keeps its aspect ratio — letterboxed on a black field, never cropped. Because it's a plain `<img>`, there's no JS hydration: the browser handles MJPEG itself.

Drop it into a `card`, a `grid`, a `tabs` panel — it composes like any other [UI component](../tutorial/ui-components.md).

## How it works

```mermaid
sequenceDiagram
    participant B as Browser <img>
    participant R as GET /golit/stream/{name}
    participant P as your @app.stream producer
    participant T as worker thread
    B->>R: request the stream
    R->>P: call producer() — a fresh generator
    loop every frame
        R->>T: next(frame)  (sync → off the loop)
        T-->>R: (H,W,3) array or JPEG bytes
        R->>R: encode + wrap as a multipart part
        R-->>B: --golitframe / image/jpeg / <bytes>
        B->>B: swap the <img> to the new frame
    end
    B->>R: tab closed → generator .close()
    R->>P: finally: release the camera
```

1. `ui.webcam` renders `<img src="/golit/stream/<name>">`.
2. The browser opens **one** request; the route looks the producer up in `app.streams` (404 if unknown).
3. Each yielded frame is encoded (arrays → JPEG) and wrapped as a `multipart/x-mixed-replace` part with boundary `golitframe`.
4. The browser replaces the `<img>` contents with each part as it arrives — that's what MJPEG *is*.
5. Closing the tab closes the generator, running your `finally`.

!!! danger "Frames are bytes, not markup"
    Unlike chat text, frames are binary JPEG, so there's no escaping concern in the stream itself. But anything you **draw** from untrusted input (a label, an OCR result) is still your responsibility to sanitize before it goes on the frame.

## Scaling & deployment

The stream is **one long-lived HTTP response per viewer**, held open on the worker that answered it — there's no fan-out and no session affinity to arrange (unlike [SSE](server-push.md) or [chat](websockets.md)). The cost model is different, though: by default a producer runs *per connection*, so N viewers of a camera means N producer runs — right for a synthetic feed or a per-session source, but wrong for one physical camera many people watch (you'd open the device N times).

### One source, many viewers: `shared=True`

For a single device fanned out to a crowd, pass `shared=True`:

```python
@app.stream("lobby", shared=True)    # one producer, however many viewers
def lobby():
    cap = cv2.VideoCapture(0)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            yield cv2.imencode(".jpg", frame)[1].tobytes()
    finally:
        cap.release()
```

Golit runs the producer **once** behind a hub: a single background pull keeps the latest frame and pushes it to every viewer's `<img>`. The producer starts when the first viewer connects and its `finally` runs when the last one leaves (so the camera is released when nobody's watching, and re-opened when someone returns). A slow viewer simply drops intermediate frames — it's MJPEG, latest wins — so one laggy client can't back up the others.

The hub is **per worker process**. Under multiple workers each opens the source once, so for a truly single hardware device pin the stream to one worker (or front it with a single capture process). For a synthetic or per-viewer feed, leave `shared` off — the default per-connection model is simpler and has nothing to share.

!!! warning "Don't buffer the stream at your proxy"
    A reverse proxy that buffers responses will stall an MJPEG feed (it waits for an end that never comes). Disable buffering and raise the read timeout on the stream path. For nginx:

    ```nginx
    location /golit/stream/ {
        proxy_pass http://golit;
        proxy_buffering off;              # push frames straight through
        proxy_read_timeout 1h;            # the response never ends on its own
    }
    ```

## The other direction: the visitor's own camera

Everything above is **server → browser** — frames originate on the server (a camera on the host, or synthetic). The mirror case is **browser → server**: stream the *visitor's own* webcam up, process each frame, and paint the result back. That's `@app.on_frame` + [`ui.camera`](../tutorial/ui-components.md):

```python
import numpy as np
import golit.ui as ui
from golit import App, create_app

app = App(title="Browser Camera")


@app.on_frame("tracker")             # ① runs per uploaded frame
def tracker(frame: np.ndarray):      # frame: (H, W, 3) uint8 RGB
    # ... run your model and draw on a copy of `frame` ...
    return frame                     # annotated RGB array (or JPEG bytes)


@app.view
def live() -> str:                   # ② capture + display
    return ui.camera("tracker", title="Your camera")


application = create_app(app)
```

The browser grabs the camera with `getUserMedia`, and over a WebSocket at `/golit/camera/<name>` it sends each captured frame as a JPEG; the server decodes it to an `(H, W, 3)` RGB array, runs your `@app.on_frame` handler, and sends the returned frame back as JPEG, which `ui.camera` paints. The handler is the inbound mirror of `@app.stream`: same array-or-bytes frames, same lazy Pillow encode, same threading — sync handlers (and every decode/encode) run in a worker thread, async handlers are awaited.

```python
ui.camera(name, *, title=None, height=384, width=640, fps=12, quality=0.6)
```

`width` caps the captured frame width in pixels (smaller = faster); `fps` is the target capture rate; `quality` is the uploaded JPEG quality (0–1). Tune these three to trade latency against fidelity.

!!! note "One frame in flight"
    The client captures the next frame only **after** the previous result comes back (then paces to `fps`). So there's never a backlog: a slow handler simply lowers the rate, and the displayed frame is always the most recent the server has finished. No queue to bound, no frames to drop.

!!! warning "Camera access needs a secure context"
    `getUserMedia` only works on **`https`** or **`localhost`**. `golit run` serves on `localhost`, so local dev is fine; in production the page must be HTTPS or the browser blocks the camera. (The [nginx upgrade headers](websockets.md#scaling) chat needs apply here too — it's a WebSocket.)

    When the camera can't start — an insecure page, a denied permission, no device, or one already in use — `ui.camera` replaces the feed with a clear, icon-labelled notice (e.g. *"Camera blocked. Allow camera access in your browser, then reload."*) rather than a stuck spinner, so the visitor knows what to fix.

Unlike a [`shared=True` `@app.stream`](#one-source-many-viewers-sharedtrue) (one producer fanned out to many), each `ui.camera` viewer has its **own** camera and its **own** WebSocket, so the handler always runs per viewer — size your CV accordingly.

## Full examples

- [`examples/webcam_stream/app.py`](https://github.com/boadzie/golit/tree/main/examples/webcam_stream) — **server → browser**. Runs with no camera: synthesizes frames with a box bouncing across the canvas and a fake `person 0.98` detection, the shape a real detector emits. Includes a commented OpenCV loop to swap in a real webcam.
- [`examples/browser_camera/app.py`](https://github.com/boadzie/golit/tree/main/examples/browser_camera) — **browser → server**. Processes the visitor's own webcam: finds the brightest region of each frame and draws a labelled box that tracks it — a dependency-light stand-in for a detector.
- [`examples/face_detect/app.py`](https://github.com/boadzie/golit/tree/main/examples/face_detect) — **browser → server**, with a *real* model. Runs OpenCV's bundled Haar-cascade face detector on each frame and boxes every face — the same `@app.on_frame` shape, with a network swapped in for the stand-in. Uses the `vision-cv` extra (adds OpenCV).

```
pip install "golit[vision]"
golit run examples/webcam_stream/app.py      # or examples/browser_camera/app.py

pip install "golit[vision-cv]"                # adds OpenCV for the face_detect example
golit run examples/face_detect/app.py
```

## Reference

- [`golit.ui.webcam`](../reference/ui.md) / [`golit.ui.camera`](../reference/ui.md) — the components.
- [`App.stream`](../reference/app.md) / [`App.on_frame`](../reference/app.md) — the producer and processor decorators.
