# Server-push updates (SSE)

Most updates are pulled by the user: they move a control, a POST runs the dirty subgraph, and the response carries the changed fragments. But some updates are **server-initiated** — there's no interaction to ride:

- a **streaming source** advances (new rows arrive),
- a **background job** finishes,
- a **shared node** is recomputed for everyone.

For these, Golit pushes over the **SSE channel**. The page holds one long-lived `GET /events` stream per session, and the server emits a named `node:<id>` event per changed view fragment, which HTMX swaps in by name. (The mechanics are in [How a change flows](../concepts/data-flow.md#path-2-sse-out-server-initiated).)

## The pub/sub channel

Server-side invalidations are published to a **`PubSub`**, and a background consumer turns each into recomputed, pushed fragments. The unit is an `Invalidation`:

```python
from golit.server import Invalidation

Invalidation(node_id="feed", session=None)
```

- `node_id` — the node that went dirty. Golit force-recomputes it and everything downstream, then pushes the changed views.
- `session` — the **scope**. `None` (default) is **global**: it fans out to every connected session. A specific session id reaches only that one client's stream.

The backend is chosen automatically by [`create_app`](../tutorial/running.md#create_app): **in-memory** on a single node, **Redis** when `GOLIT_REDIS_URL` is set (so one publish reaches every worker). You can also pass one explicitly.

## Example: a live ticking clock

A source that returns the current time, a view that shows it, and a background task that publishes an invalidation every second:

```python title="clock.py"
import asyncio
import datetime

from golit import App, create_app
from golit.server import Invalidation

app = App(title="Live Clock")


@app.source
def now() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


@app.view
def clock(now: str) -> str:
    return f"<p class='font-mono text-5xl'>{now}</p>"


async def _tick(litestar_app) -> None:
    while True:
        await asyncio.sleep(1)
        # Global scope: every connected session gets the push.
        await litestar_app.state.pubsub.publish(Invalidation(node_id="now"))


async def start_ticker(litestar_app) -> None:
    # Keep a reference so the task isn't garbage-collected.
    litestar_app.state.ticker = asyncio.create_task(_tick(litestar_app))


application = create_app(app, on_startup=[start_ticker])
```

Run it with `golit run clock.py` and watch the time update every second, with no interaction — the push path in action.

!!! note "Why `refresh` forces the source"
    A source with no inputs would normally memo-hit forever. The push path **forces** the named node to re-execute (it's the explicit "this is dirty for an external reason" signal), so `now` produces a fresh value, `clock` sees a changed input, and its fragment is pushed. Nodes further downstream still memo normally.

## Lifecycle hooks

`create_app` accepts `on_startup` and `on_shutdown` lists. Each hook receives the Litestar application, so you can reach `app.state.pubsub` (the chosen backend) and `app.state.sessions`. Golit's own SSE consumer is already registered; your hooks run alongside it.

```python
create_app(app, on_startup=[start_ticker], on_shutdown=[stop_ticker])
```

Use startup hooks to launch background producers (tickers, queue consumers, file watchers) that publish invalidations; use shutdown hooks to cancel them cleanly.

## Choosing the backend explicitly

```python
from golit import create_app
from golit.server import RedisPubSub

application = create_app(app, pubsub=RedisPubSub("redis://redis:6379"))
```

Both backends implement the same `PubSub` protocol (`publish` + `listen`), so the SSE layer doesn't change. The Redis backend is what fans invalidations across a multi-worker fleet — see [Deployment & scaling](deployment.md).

## What does *not* go through pub/sub

Only small JSON invalidation messages (`node_id`, `session`) travel the channel. **Session state never does** — the kernel graph and the Polars values stay worker-local. Serializing DataFrames on every interaction would defeat the whole "cost ∝ change" thesis. That locality is the subject of [Sessions & state](sessions.md).
