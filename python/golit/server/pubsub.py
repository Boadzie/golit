"""Invalidation fan-out.

When a node goes dirty for a reason the requesting client didn't trigger — a
streaming source advancing, a background job finishing, a shared node recomputed
for everyone — the invalidation is published here and fans out to every worker's
SSE streams.

Single-node uses :class:`InMemoryPubSub`. A Redis-backed implementation of the
same :class:`PubSub` protocol drops in for a horizontally-scaled fleet (publish
once to Redis, every worker receives it) with no change to the SSE layer.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Invalidation:
    """A node went dirty server-side. ``session`` scopes the fan-out: a specific
    session id reaches only that client; ``None`` is global (every session)."""

    node_id: str
    session: str | None = None


class PubSub(Protocol):
    async def publish(self, inv: Invalidation) -> None: ...
    def listen(self) -> AsyncIterator[Invalidation]: ...


class InMemoryPubSub:
    """Process-local pub/sub: every listener receives every invalidation, mirroring
    Redis pub/sub fan-out semantics on a single node."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[Invalidation]] = []

    async def publish(self, inv: Invalidation) -> None:
        for queue in self._subscribers:
            queue.put_nowait(inv)

    async def listen(self) -> AsyncIterator[Invalidation]:
        queue: asyncio.Queue[Invalidation] = asyncio.Queue()
        self._subscribers.append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.remove(queue)
