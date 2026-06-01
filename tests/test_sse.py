"""SSE push channel: pub/sub fan-out and server-initiated fragment dispatch."""

from __future__ import annotations

import asyncio

import polars as pl
from golit import App
from golit.server.pubsub import InMemoryPubSub, Invalidation
from golit.server.session import SessionManager
from golit.server.sse import SSEManager


def build_sessions() -> SessionManager:
    """A graph whose source changes on every (re)compute, so a refresh always
    produces a new view fragment."""
    counter = {"n": 0}
    app = App()

    @app.source
    def data() -> pl.DataFrame:
        counter["n"] += 1
        return pl.DataFrame({"x": [counter["n"]]})

    @app.view
    def view(data: pl.DataFrame) -> str:
        return f"<p>n={data['x'][0]}</p>"

    return SessionManager(app)


async def test_inmemory_pubsub_fans_out():
    ps = InMemoryPubSub()
    listener = ps.listen()
    pending = asyncio.ensure_future(listener.__anext__())
    await asyncio.sleep(0.01)  # let the listener subscribe
    await ps.publish(Invalidation("data", "s1"))
    inv = await asyncio.wait_for(pending, 1)
    assert inv == Invalidation("data", "s1")
    await listener.aclose()


async def test_dispatch_pushes_changed_fragment_to_session():
    sessions = build_sessions()
    sid, session, _ = sessions.get_or_create(None)
    session.initial_render()  # n=1
    sse = SSEManager(sessions, InMemoryPubSub())
    queue = sse.connect(sid)

    await sse.dispatch(Invalidation("data", sid))  # refresh source → n=2

    view_id, content = queue.get_nowait()
    assert view_id == "view"
    assert "n=2" in content
    assert queue.empty()


async def test_global_dispatch_reaches_every_session():
    sessions = build_sessions()
    sid1, s1, _ = sessions.get_or_create(None)
    sid2, s2, _ = sessions.get_or_create(None)
    s1.initial_render()
    s2.initial_render()
    sse = SSEManager(sessions, InMemoryPubSub())
    q1, q2 = sse.connect(sid1), sse.connect(sid2)

    await sse.dispatch(Invalidation("data", session=None))  # global

    assert not q1.empty() and not q2.empty()
    assert q1.get_nowait()[0] == "view"
    assert q2.get_nowait()[0] == "view"


async def test_stream_yields_named_node_event():
    sessions = build_sessions()
    sid, session, _ = sessions.get_or_create(None)
    session.initial_render()
    sse = SSEManager(sessions, InMemoryPubSub())

    stream = sse.stream(sid)
    pending = asyncio.ensure_future(stream.__anext__())
    await asyncio.sleep(0.01)  # let the stream register its queue
    await sse.dispatch(Invalidation("data", sid))

    message = await asyncio.wait_for(pending, 1)
    assert message.event == "node:view"
    assert "n=" in message.data
    await stream.aclose()


async def test_disconnect_cleans_up():
    sessions = build_sessions()
    sid, session, _ = sessions.get_or_create(None)
    session.initial_render()
    sse = SSEManager(sessions, InMemoryPubSub())
    queue = sse.connect(sid)
    sse.disconnect(sid, queue)
    # No queues left for the session → a dispatch is a no-op, not an error.
    await sse.dispatch(Invalidation("data", sid))
    assert sid not in sse._queues
