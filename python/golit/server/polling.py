"""Live polled sources — the runtime behind :meth:`golit.App.poll`.

A polled source is the home for *external data that changes on its own*: a Google Sheet, an
API, a file on disk. The user's function fetches it; a background task here runs that fetch
every ``interval`` seconds, hashes the result, and **only when the content changes** updates the
shared cache and publishes an :class:`Invalidation`. Golit's SSE channel then force-recomputes
the source node and re-renders the dependent views to every connected browser — the same
server-side-invalidation path streaming sources use.

The hash makes the work proportional to *change*: identical fetches cost one md5 and push
nothing. One poller runs per worker process (like ``@app.stream``).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import logging
from typing import Any

import anyio
from litestar import Litestar

from ..app import App
from .pubsub import Invalidation

_log = logging.getLogger("golit.poll")


def _poll_hash(value: Any) -> str:
    """A content fingerprint for change detection — cheap and stable across fetches."""
    if value is None:
        return ""
    if hasattr(value, "write_csv"):  # a polars DataFrame (or anything CSV-serializable)
        payload = value.write_csv().encode()
    elif isinstance(value, (bytes, bytearray)):
        payload = bytes(value)
    else:
        payload = repr(value).encode()
    return hashlib.md5(payload).hexdigest()


async def _call(fn: Any) -> Any:
    """Run the fetch — awaited if async, else off the event loop in a worker thread."""
    if inspect.iscoroutinefunction(fn):
        return await fn()
    return await anyio.to_thread.run_sync(fn)


async def _poll_loop(litestar: Litestar, app: App, name: str, fn: Any, interval: float) -> None:
    last: str | None = None
    while True:
        try:
            value = await _call(fn)
            digest = _poll_hash(value)
            if digest != last:
                last = digest
                app.poll_cache[name] = value
                await litestar.state.pubsub.publish(Invalidation(node_id=name, session=None))
        except asyncio.CancelledError:
            raise
        except Exception:
            # A transient fetch failure shouldn't kill the poller — log and retry next tick,
            # keeping the last good value on screen.
            _log.exception("poll %r failed", name)
        await asyncio.sleep(interval)


async def start_pollers(litestar: Litestar) -> None:
    """Launch one background task per registered polled source (an on_startup hook)."""
    app: App = litestar.state.app_blueprint
    litestar.state.poll_tasks = [
        asyncio.ensure_future(_poll_loop(litestar, app, name, fn, interval))
        for name, (fn, interval) in app.pollers.items()
    ]


async def stop_pollers(litestar: Litestar) -> None:
    """Cancel the poller tasks on shutdown."""
    tasks = getattr(litestar.state, "poll_tasks", [])
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
