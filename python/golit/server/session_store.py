"""Durable session state — the *shared* layer behind the worker-local cache.

A :class:`~golit.server.session.SessionManager` keeps live :class:`Session`
objects (kernel graph + Polars values) in memory on the worker that created them.
That's deliberate: serializing DataFrames per interaction would defeat the
"cost ∝ change" thesis. What a *shared* store needs to hold for horizontal scaling
is therefore not the frames but the small thing they're derived from — the
**input/widget state** (e.g. ``threshold=30``). Given the (deterministic) app
blueprint plus those inputs, any worker can rebuild the frames locally by replaying
them. So this layer persists only ``sid → {input_id: raw_value}``.

:class:`InMemorySessionStore` is the single-node default: there is no separate
durable layer, the live ``Session`` *is* the state, so its methods are no-ops and
``load`` never reconstructs. :class:`RedisSessionStore` (selected by
``GOLIT_REDIS_URL``) persists the input map to Redis so a request that lands on a
worker without the live session can reconstruct it — no frames cross the wire, and
sticky routing is no longer required for the request path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from redis import Redis

DEFAULT_URL = "redis://localhost:6379"
DEFAULT_PREFIX = "golit:sess:"
DEFAULT_TTL_SECONDS = 60 * 60


@runtime_checkable
class SessionStore(Protocol):
    """The durable input-state layer. Implementations must be safe to call from a
    worker thread (the manager offloads session work off the event loop)."""

    def load(self, sid: str) -> dict[str, str] | None:
        """The stored ``{input_id: raw_value}`` for ``sid``, or ``None`` if there is
        nothing to reconstruct from (a brand-new or input-unchanged session)."""
        ...

    def save_input(self, sid: str, input_id: str, value: str) -> None:
        """Persist one input change so another worker can replay it."""
        ...


class InMemorySessionStore:
    """Single-node default: no shared durable layer. The live :class:`Session`
    holds all state, so there is nothing to persist and nothing to reconstruct."""

    def load(self, sid: str) -> dict[str, str] | None:
        return None

    def save_input(self, sid: str, input_id: str, value: str) -> None:
        return None


class RedisSessionStore:
    """Persist each session's input map to Redis for cross-worker reconstruction.

    Only scalar input *values* are stored (one Redis hash per session), never the
    derived frames. ``client`` may be injected (e.g. a ``fakeredis`` instance in
    tests); otherwise a sync client is built lazily from ``url`` on first use, so
    importing this module never requires a live Redis. The hash TTL is refreshed on
    every write, mirroring the manager's idle-eviction window."""

    def __init__(
        self,
        url: str = DEFAULT_URL,
        *,
        prefix: str = DEFAULT_PREFIX,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        client: Redis | None = None,
    ) -> None:
        self._url = url
        self._prefix = prefix
        self._ttl = ttl_seconds
        self._client = client

    def _redis(self) -> Redis:
        if self._client is None:
            import redis

            self._client = redis.from_url(self._url)
        return self._client

    def _key(self, sid: str) -> str:
        return f"{self._prefix}{sid}"

    def load(self, sid: str) -> dict[str, str] | None:
        raw = self._redis().hgetall(self._key(sid))
        if not raw:
            return None

        def _text(v: object) -> str:
            return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)

        return {_text(k): _text(v) for k, v in raw.items()}

    def save_input(self, sid: str, input_id: str, value: str) -> None:
        key = self._key(sid)
        client = self._redis()
        client.hset(key, input_id, value)
        if self._ttl > 0:
            client.expire(key, self._ttl)
