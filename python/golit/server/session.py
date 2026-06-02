"""Per-client session management.

A session id rides in a cookie. The manager keeps one live :class:`Session`
(kernel graph + value registry) per id, **worker-local** — that's the perf thesis
(Polars frames never serialized). Two layers sit behind one interface:

* a bounded in-memory cache of live sessions (LRU + TTL, so a long-running server
  doesn't accumulate a session per browser tab that ever connected), and
* a :class:`~golit.server.session_store.SessionStore` holding only the small
  *input* state durably. Single-node uses the no-op in-memory store. With Redis
  (``GOLIT_REDIS_URL``) the input map is shared, so a request landing on a worker
  that lacks the live session **reconstructs** it locally — new session + replay of
  the stored inputs — instead of failing or needing sticky routing.

The request-path methods (:meth:`prepare`, :meth:`prepare_and_update`) are sync and
CPU-bound; the routes offload them to a worker thread under a **per-session lock**
(:meth:`lock_for`) so concurrent clients parallelize while same-session requests
stay serialized (the kernel graph is mutated in place).
"""

from __future__ import annotations

import asyncio
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from ..app import App
from ..engine import Session
from ..rendering import render_value
from .session_store import InMemorySessionStore, SessionStore

COOKIE = "golit_session"

DEFAULT_MAX_SESSIONS = 10_000
DEFAULT_TTL_SECONDS = 60 * 60  # evict a session idle for an hour


@dataclass
class _Entry:
    session: Session
    seen: float  # monotonic timestamp of last access


class SessionManager:
    """A bounded, thread-safe map of session id → live :class:`Session`, backed by
    a durable :class:`SessionStore` for the input state.

    Idle sessions expire after ``ttl_seconds`` and the least-recently-used is shed
    once the live count would exceed ``max_sessions`` (set either to ``0`` to
    disable). ``store`` defaults to the no-op in-memory store (single-node)."""

    def __init__(
        self,
        app: App,
        *,
        store: SessionStore | None = None,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.app = app
        self.store: SessionStore = store or InMemorySessionStore()
        self.max_sessions = max_sessions
        self.ttl_seconds = ttl_seconds
        self._sessions: OrderedDict[str, _Entry] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}
        self._lock = threading.Lock()

    def _new_session(self) -> Session:
        return Session(self.app, view_renderer=lambda _id, value: render_value(value))

    def _drop(self, sid: str) -> None:
        """Remove a session (and its lock). Caller holds the lock."""
        del self._sessions[sid]
        self._locks.pop(sid, None)

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
            self._drop(sid)

    def _touch(self, sid: str, now: float) -> Session:
        """Mark a session most-recently-used and return it. Caller holds the lock."""
        entry = self._sessions[sid]
        entry.seen = now
        self._sessions.move_to_end(sid)
        return entry.session

    def _insert(self, sid: str, session: Session, now: float) -> None:
        """Cache a freshly built session, enforcing the LRU cap. Caller holds lock."""
        self._sessions[sid] = _Entry(session, now)
        self._sessions.move_to_end(sid)
        if self.max_sessions > 0:
            while len(self._sessions) > self.max_sessions:
                old_sid, _ = next(iter(self._sessions.items()))
                self._drop(old_sid)  # shed the oldest

    def get_or_create(self, sid: str | None) -> tuple[str, Session, bool]:
        """Resolve a session by cookie id. Returns ``(sid, session, created)``.

        ``created`` is ``True`` only for a brand-new session, signalling the caller
        to set the cookie *and* run the initial render. A session **reconstructed**
        from the durable store is returned ``created=False`` and already rendered
        (its inputs replayed) — the client already holds the cookie."""
        now = time.monotonic()
        with self._lock:
            self._evict_expired(now)
            if sid and sid in self._sessions:
                return sid, self._touch(sid, now), False

        # Local miss. Try to reconstruct from the durable store (Redis), else this
        # is a genuinely new session. Heavy work (render/replay) runs outside the
        # lock so other sessions aren't serialized behind it.
        inputs = self.store.load(sid) if sid else None
        session = self._new_session()
        if inputs:
            session.initial_render()
            for input_id, value in inputs.items():
                try:
                    session.update(input_id, value)  # replay the stored input
                except KeyError:
                    continue  # input no longer in the graph (app changed) — skip
            created = False
        else:
            created = True  # caller renders + sets the cookie
        sid = sid or secrets.token_urlsafe(16)

        with self._lock:
            # A concurrent request may have built it first; prefer the cached one.
            if sid in self._sessions:
                return sid, self._touch(sid, time.monotonic()), False
            self._insert(sid, session, time.monotonic())
            return sid, session, created

    def get(self, sid: str | None) -> Session | None:
        """Fast, local-only lookup (no reconstruction) — used by the SSE dispatch
        loop, which must not block on store I/O or a heavy rebuild."""
        if not sid:
            return None
        now = time.monotonic()
        with self._lock:
            self._evict_expired(now)
            if sid not in self._sessions:
                return None
            return self._touch(sid, now)

    # -- request-path entry points (offloaded to a thread by the routes) --------
    def prepare(self, cookie_sid: str | None) -> tuple[str, Session, bool]:
        """Resolve a render-ready session for a request: reuse/reconstruct/create,
        running the initial render for a brand-new one."""
        sid, session, created = self.get_or_create(cookie_sid)
        if created:
            session.initial_render()
        return sid, session, created

    def prepare_and_update(
        self, cookie_sid: str | None, input_id: str, raw: object
    ) -> tuple[str, Session, bool, dict[str, str]]:
        """Resolve the session, commit the input change, persist it for other
        workers, and return the changed fragments. Raises ``KeyError`` for an
        unknown input (propagated to a 404)."""
        sid, session, created = self.prepare(cookie_sid)
        fragments = session.update(input_id, raw)
        if isinstance(raw, str):
            self.store.save_input(sid, input_id, raw)  # only replayable scalars
        return sid, session, created, fragments

    def lock_for(self, sid: str | None) -> asyncio.Lock:
        """The per-session lock serializing that session's requests. A missing id
        (brand-new client, no cookie yet) gets a fresh, uncontended lock."""
        if not sid:
            return asyncio.Lock()
        with self._lock:
            lock = self._locks.get(sid)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[sid] = lock
            return lock

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
