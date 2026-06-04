# Video streams (webcam / computer vision)

Some views aren't a fragment that re-renders on a change — they're a **continuous picture**: a camera feed, a detector drawing boxes on each frame, a synthetic visualization that animates on its own. Golit serves those as a **server-side MJPEG stream**: the server pushes a never-ending sequence of JPEG frames and the browser plays them in a plain `<img>`.

This stays on-brand with the rest of Golit — no client framework, no canvas glue, no JSON-to-pixels code. The browser plays `multipart/x-mixed-replace` natively, and the stream lives **outside** the reactive graph, so the live view holds one stable connection and never re-renders mid-frame.

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
    participant B as Browser &lt;img&gt;
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

The stream is **one long-lived HTTP response per viewer**, held open on the worker that answered it — there's no fan-out and no session affinity to arrange (unlike [SSE](server-push.md) or [chat](websockets.md)). The cost model is different, though: a producer runs *per connection*, so N viewers of a camera means N producer runs. For a single shared source watched by many, have one producer read the device and publish frames to a queue that each request drains — the same hub shape chat uses.

!!! warning "Don't buffer the stream at your proxy"
    A reverse proxy that buffers responses will stall an MJPEG feed (it waits for an end that never comes). Disable buffering and raise the read timeout on the stream path. For nginx:

    ```nginx
    location /golit/stream/ {
        proxy_pass http://golit;
        proxy_buffering off;              # push frames straight through
        proxy_read_timeout 1h;            # the response never ends on its own
    }
    ```

## Browser uploads (the other direction)

This page is **server → browser**: the frames originate on the server (a camera attached to the host, or synthetic). Streaming the *user's own* webcam up to the server for processing — `getUserMedia` → upload → server-side CV → annotated frames back — is the mirror-image case and reuses this exact display path for the return leg. That's a planned follow-on; the server-side stream here is the foundation.

## Full example

[`examples/webcam_stream/app.py`](https://github.com/boadzie/golit/tree/main/examples/webcam_stream) runs with **no camera** — it synthesizes frames with a box bouncing across the canvas and a fake `person 0.98` detection drawn on each one, the shape a real detector emits. It includes a commented OpenCV loop to swap in an actual webcam.

```
pip install "golit[vision]"
golit run examples/webcam_stream/app.py
```

## Reference

- [`golit.ui.webcam`](../reference/ui.md) — the component.
- [`App.stream`](../reference/app.md) — the producer decorator.
