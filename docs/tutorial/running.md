# Running your app

A Golit blueprint (`App`) isn't itself a web server — you turn it into an [ASGI](https://asgi.readthedocs.io/) application and serve that. There are two ways, and they meet in the middle.

## `create_app`

`create_app(app)` wires your blueprint into a runnable Litestar ASGI application:

```python
from golit import create_app

application = create_app(app)
```

This is the conventional last line of an app module. The resulting `application` is a standard ASGI app — any ASGI server can serve it:

```bash
uvicorn app:application
# or gunicorn, hypercorn, …
```

`create_app` takes a few keyword options for advanced use:

```python
create_app(app, *, pubsub=None, on_startup=[…], on_shutdown=[…])
```

- `pubsub` overrides the SSE fan-out backend (default: chosen from the environment — Redis when `GOLIT_REDIS_URL` is set, in-memory otherwise). See [Server-push updates](../advanced/server-push.md).
- `on_startup` / `on_shutdown` add lifecycle hooks — e.g. to launch a background ticker that pushes updates.

## `golit run`

The CLI is the quickest path during development:

```bash
golit run app.py
```

It loads the file and launches it under Uvicorn. The file may expose either:

- a Litestar `application` (e.g. `application = create_app(app)`), **or**
- a bare Golit `app` (an `App`), which `golit run` wraps with `create_app` automatically.

So even this minimal module runs:

```python title="app.py"
from golit import App, slider

app = App(title="Minimal")

@app.view
def out(n: int = slider(0, 10)) -> str:
    return f"<p>{n}</p>"

# no create_app needed — `golit run` finds `app`
```

### Options

| Flag | Default | Meaning |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Bind address. |
| `--port` | `8000` | Port. |
| `--workers` | `1` | Worker processes. |

```bash
golit run app.py --host 0.0.0.0 --port 9000
```

!!! warning "`--workers > 1` is for local testing, not production"
    Golit keeps **session state worker-local** (it's what makes recompute cheap). Uvicorn's `--workers` share one socket with no session affinity, so a returning client can land on a worker that doesn't hold its state. `golit run --workers N` prints a warning and exists for convenience. The production path is **N single-worker instances behind a sticky load balancer + Redis** — see [Deployment & scaling](../advanced/deployment.md).

## `python -m golit`

`golit` and `python -m golit` are equivalent entry points:

```bash
python -m golit run app.py
```

## The routes it serves

Once running, your app exposes three endpoints (you rarely call them directly — HTMX does):

| Route | Purpose |
| --- | --- |
| `GET /` | The full page: controls + every view, for a session. |
| `POST /node/{input_id}` | Commit an input change; returns the changed view fragments as out-of-band swaps. |
| `GET /events` | The SSE push channel: one long-lived stream per session. |

How these fit together is the subject of **[How a change flows](../concepts/data-flow.md)**.

## Next

You've finished the tutorial. Two good directions:

- **[Concepts](../concepts/index.md)** — understand *why* it's fast.
- **[Advanced](../advanced/index.md)** — server-push updates, custom rendering, and deployment.
