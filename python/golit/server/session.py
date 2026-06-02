"""Per-client session management.

A session id rides in a cookie. The manager keeps one :class:`Session` (kernel
graph + value registry) per id, server-side. State is per-session; the :class:`App`
blueprint is shared.

The store is **bounded** so a long-running server doesn't accumulate a session per
browser tab that ever connected. Entries fall out two ways: by **TTL** (idle longer
than ``ttl_seconds``) and by **LRU** (the least-recently-used session is dropped
once the count would exceed ``max_sessions``). Access order is tracked with an
``OrderedDict`` — every touch moves the entry to the back — so eviction is cheap:
expired sessions are exactly the ones at the front. A lock guards the map so it is
safe under threaded as well as async workers.

Single-node only for now — a Redis-backed store slots in here behind the same
interface for horizontal scaling.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from ..app import App
from ..engine import Session
from ..rendering import render_value

COOKIE = "golit_session"

DEFAULT_MAX_SESSIONS = 10_000
DEFAULT_TTL_SECONDS = 60 * 60  # evict a session idle for an hour


@dataclass
class _Entry:
    session: Session
    seen: float  # monotonic timestamp of last access


class SessionManager:
    """A bounded, thread-safe map of session id → :class:`Session`.

    Eviction keeps memory flat under load: idle sessions expire after
    ``ttl_seconds``, and the least-recently-used session is dropped once the live
    count would exceed ``max_sessions``. Set either to ``0`` to disable that bound."""

    def __init__(
        self,
        app: App,
        *,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.app = app
        self.max_sessions = max_sessions
        self.ttl_seconds = ttl_seconds
        self._sessions: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.Lock()

    def _new_session(self) -> Session:
        return Session(self.app, view_renderer=lambda _id, value: render_value(value))

    def _evict_expired(self, now: float) -> None:
        """Drop entries idle past the TTL. Because the map is ordered by access
        recency, the stale ones are a prefix — stop at the first live entry.
        Caller holds the lock."""
        if self.ttl_seconds <= 0:
            return
        cutoff = now - self.ttl_seconds
        while self._sessions:
            sid, entry = next(iter(self._sessions.items()))
            if entry.seen >= cutoff:
                break
            del self._sessions[sid]

    def _touch(self, sid: str, now: float) -> Session:
        """Mark a session most-recently-used and return it. Caller holds the lock."""
        entry = self._sessions[sid]
        entry.seen = now
        self._sessions.move_to_end(sid)
        return entry.session

    def get_or_create(self, sid: str | None) -> tuple[str, Session, bool]:
        """Resolve a session by cookie id, creating one if absent/unknown/expired.

        Returns ``(sid, session, created)`` — ``created`` signals the caller to
        set the cookie and run the initial render."""
        now = time.monotonic()
        with self._lock:
            self._evict_expired(now)
            if sid and sid in self._sessions:
                return sid, self._touch(sid, now), False

            sid = sid or secrets.token_urlsafe(16)
            self._sessions[sid] = _Entry(self._new_session(), now)
            self._sessions.move_to_end(sid)
            if self.max_sessions > 0:
                while len(self._sessions) > self.max_sessions:
                    self._sessions.popitem(last=False)  # shed the oldest
            return sid, self._sessions[sid].session, True

    def get(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        now = time.monotonic()
        with self._lock:
            self._evict_expired(now)
            if sid not in self._sessions:
                return None
            return self._touch(sid, now)

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
