"""Build a Litestar ASGI app from a Golit :class:`App`."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from litestar import Litestar
from litestar.datastructures import State

from ..app import App
from .chat import ChatHub
from .processing import camera
from .pubsub import InMemoryPubSub, PubSub
from .routes import chat_ws, events, index, update_node
from .session import SessionManager
from .session_store import InMemorySessionStore, SessionStore
from .sse import SSEManager
from .streaming import stream
from .tiles import tile
from .vector_tiles import vector_tile

LifecycleHook = Callable[..., Any]

REDIS_URL_ENV = "GOLIT_REDIS_URL"


def pubsub_from_env() -> PubSub:
    """Pick the fan-out backend from the environment: Redis when
    ``GOLIT_REDIS_URL`` is set (multi-worker), in-memory otherwise (single-node).
    Redis is an optional dependency, imported only when actually selected."""
    url = os.environ.get(REDIS_URL_ENV)
    if url:
        from .redis_pubsub import RedisPubSub

        return RedisPubSub(url)
    return InMemoryPubSub()


def session_store_from_env() -> SessionStore:
    """Pick the durable session-state backend: a Redis input-replay store when
    ``GOLIT_REDIS_URL`` is set (so any worker can reconstruct a session from its
    inputs), in-memory otherwise (single-node, nothing to persist). Mirrors
    :func:`pubsub_from_env`; only input scalars are stored, never frames."""
    url = os.environ.get(REDIS_URL_ENV)
    if url:
        from .session_store import RedisSessionStore

        return RedisSessionStore(url)
    return InMemorySessionStore()


async def _start_sse(app: Litestar) -> None:
    app.state.sse_task = asyncio.create_task(app.state.sse.run())


async def _stop_sse(app: Litestar) -> None:
    task = getattr(app.state, "sse_task", None)
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    aclose = getattr(getattr(app.state, "pubsub", None), "aclose", None)
    if aclose is not None:
        await aclose()  # release the Redis client, if any


def create_app(
    app: App,
    *,
    pubsub: PubSub | None = None,
    session_store: SessionStore | None = None,
    on_startup: list[LifecycleHook] | None = None,
    on_shutdown: list[LifecycleHook] | None = None,
) -> Litestar:
    """Wire a Golit blueprint into a runnable Litestar application.

    ``pubsub`` overrides the SSE fan-out backend and ``session_store`` the durable
    session-state backend; by default each is chosen from the environment (Redis
    when ``GOLIT_REDIS_URL`` is set, in-memory otherwise). Extra ``on_startup``
    hooks can launch background tasks (e.g. a ticker that publishes invalidations
    to ``app.state.pubsub`` for the SSE channel)."""
    app.build()
    sessions = SessionManager(app, store=session_store or session_store_from_env())
    if pubsub is None:
        pubsub = pubsub_from_env()
    sse = SSEManager(sessions, pubsub)
    chat = ChatHub(app)
    return Litestar(
        route_handlers=[
            index, update_node, events, chat_ws, tile, vector_tile, stream, camera
        ],
        state=State(
            {"sessions": sessions, "pubsub": pubsub, "sse": sse, "chat": chat,
             "streams": app.streams, "frame_handlers": app.frame_handlers}
        ),
        on_startup=[_start_sse, *(on_startup or [])],
        on_shutdown=[_stop_sse, *(on_shutdown or [])],
    )
