"""Server-Sent Events: the server→client push channel.

Each session holds one or more long-lived EventSource connections; this manager
keeps a queue per connection. A background consumer reads invalidations from the
:class:`PubSub`, recomputes the affected session(s), and pushes each changed view
fragment as a named event ``node:<id>`` — which HTMX's SSE extension swaps into
``#<id>`` by name, the same fragment-by-name contract as the POST path.
"""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from collections.abc import AsyncIterator

from litestar.response import ServerSentEventMessage

from .pubsub import Invalidation, PubSub
from .session import SessionManager

# A queued push: (view node id, rendered fragment content).
Event = tuple[str, str]

# Keepalive cadence: how often an idle stream emits a comment so proxies with a
# short idle timeout don't drop the connection. Tunable via env for fronting
# proxies (and the concurrency benchmark, which samples loop responsiveness here).
DEFAULT_PING_INTERVAL = float(os.environ.get("GOLIT_SSE_PING_INTERVAL", "15.0"))


class SSEManager:
    def __init__(self, sessions: SessionManager, pubsub: PubSub) -> None:
        self.sessions = sessions
        self.pubsub = pubsub
        self._queues: dict[str, list[asyncio.Queue[Event]]] = defaultdict(list)

    # -- connection registry ----------------------------------------------
    def connect(self, sid: str) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._queues[sid].append(queue)
        return queue

    def disconnect(self, sid: str, queue: asyncio.Queue[Event]) -> None:
        queues = self._queues.get(sid)
        if not queues:
            return
        if queue in queues:
            queues.remove(queue)
        if not queues:
            del self._queues[sid]

    # -- invalidation dispatch --------------------------------------------
    async def dispatch(self, inv: Invalidation) -> None:
        """Recompute the affected session(s) and enqueue the changed fragments."""
        targets = [inv.session] if inv.session is not None else list(self._queues)
        for sid in targets:
            session = self.sessions.get(sid)
            if session is None:
                continue
            for view_id, content in session.refresh(inv.node_id).items():
                for queue in self._queues.get(sid, []):
                    queue.put_nowait((view_id, content))

    async def run(self) -> None:
        """Background consumer: drain the pub/sub and dispatch forever."""
        async for inv in self.pubsub.listen():
            await self.dispatch(inv)

    # -- per-connection event stream --------------------------------------
    async def stream(
        self, sid: str, *, ping_interval: float = DEFAULT_PING_INTERVAL
    ) -> AsyncIterator[ServerSentEventMessage]:
        queue = self.connect(sid)
        try:
            while True:
                try:
                    view_id, content = await asyncio.wait_for(queue.get(), ping_interval)
                    yield ServerSentEventMessage(event=f"node:{view_id}", data=content)
                except TimeoutError:
                    yield ServerSentEventMessage(comment="ping")  # keep proxies open
        finally:
            self.disconnect(sid, queue)
