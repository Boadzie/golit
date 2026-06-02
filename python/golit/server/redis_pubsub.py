"""Redis-backed PubSub — cross-worker invalidation fan-out for a scaled fleet.

Single-node uses :class:`~golit.server.pubsub.InMemoryPubSub`, where publish and
listen live in one process. With multiple workers (or hosts), a server-side
invalidation must reach the worker that holds *each* affected client's SSE
connection. Redis pub/sub delivers one ``publish`` to every subscribed worker, so
this class implements the same :class:`~golit.server.pubsub.PubSub` protocol and
drops into ``create_app`` with no change to the SSE layer.

What does **not** go through Redis: per-session state (the kernel graph and the
Polars values). That stays worker-local — serializing DataFrames per interaction
would defeat the whole "cost ∝ change" thesis. The price is *session affinity*:
a client's POST and its ``/events`` stream must land on the worker that owns its
state. See ``DEPLOYMENT.md``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from .pubsub import Invalidation

if TYPE_CHECKING:
    from redis.asyncio import Redis

DEFAULT_URL = "redis://localhost:6379"
DEFAULT_CHANNEL = "golit:invalidations"


class RedisPubSub:
    """Fan invalidations out across workers via a Redis pub/sub channel.

    A drop-in for :class:`InMemoryPubSub`. ``client`` may be injected (e.g. a
    ``fakeredis`` instance in tests); otherwise a client is built lazily from
    ``url`` on first use, so importing this module never requires a live Redis.
    """

    def __init__(
        self,
        url: str = DEFAULT_URL,
        *,
        channel: str = DEFAULT_CHANNEL,
        client: Redis | None = None,
    ) -> None:
        self._url = url
        self._channel = channel
        self._client = client

    def _redis(self) -> Redis:
        if self._client is None:
            import redis.asyncio as redis

            self._client = redis.from_url(self._url)
        return self._client

    async def publish(self, inv: Invalidation) -> None:
        payload = json.dumps({"node_id": inv.node_id, "session": inv.session})
        await self._redis().publish(self._channel, payload)

    async def listen(self) -> AsyncIterator[Invalidation]:
        pubsub = self._redis().pubsub()
        await pubsub.subscribe(self._channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue  # skip subscribe/unsubscribe confirmations
                data = message["data"]
                if isinstance(data, (bytes, bytearray)):
                    data = data.decode()
                obj = json.loads(data)
                yield Invalidation(node_id=obj["node_id"], session=obj.get("session"))
        finally:
            await pubsub.unsubscribe(self._channel)
            await pubsub.aclose()

    async def aclose(self) -> None:
        """Release the shared client (called from the server shutdown hook)."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
