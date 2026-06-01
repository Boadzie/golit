"""Build a Litestar ASGI app from a Golit :class:`App`."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from litestar import Litestar
from litestar.datastructures import State

from ..app import App
from .pubsub import InMemoryPubSub
from .routes import events, index, update_node
from .session import SessionManager
from .sse import SSEManager

LifecycleHook = Callable[..., Any]


async def _start_sse(app: Litestar) -> None:
    app.state.sse_task = asyncio.create_task(app.state.sse.run())


async def _stop_sse(app: Litestar) -> None:
    task = getattr(app.state, "sse_task", None)
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def create_app(
    app: App,
    *,
    on_startup: list[LifecycleHook] | None = None,
    on_shutdown: list[LifecycleHook] | None = None,
) -> Litestar:
    """Wire a Golit blueprint into a runnable Litestar application.

    Extra ``on_startup`` hooks can launch background tasks (e.g. a ticker that
    publishes invalidations to ``app.state.pubsub`` for the SSE channel)."""
    app.build()
    sessions = SessionManager(app)
    pubsub = InMemoryPubSub()
    sse = SSEManager(sessions, pubsub)
    return Litestar(
        route_handlers=[index, update_node, events],
        state=State({"sessions": sessions, "pubsub": pubsub, "sse": sse}),
        on_startup=[_start_sse, *(on_startup or [])],
        on_shutdown=[_stop_sse, *(on_shutdown or [])],
    )
