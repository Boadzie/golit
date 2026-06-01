"""Per-client session management.

A session id rides in a cookie. The manager keeps one :class:`Session` (kernel
graph + value registry) per id, server-side. State is per-session; the :class:`App`
blueprint is shared. Single-node only for now — a Redis-backed store slots in here
behind the same interface for horizontal scaling.
"""

from __future__ import annotations

import secrets

from ..app import App
from ..engine import Session
from ..rendering import render_value

COOKIE = "golit_session"


class SessionManager:
    def __init__(self, app: App) -> None:
        self.app = app
        self._sessions: dict[str, Session] = {}

    def _new_session(self) -> Session:
        return Session(self.app, view_renderer=lambda _id, value: render_value(value))

    def get_or_create(self, sid: str | None) -> tuple[str, Session, bool]:
        """Resolve a session by cookie id, creating one if absent/unknown.

        Returns ``(sid, session, created)`` — ``created`` signals the caller to
        set the cookie and run the initial render."""
        if sid and sid in self._sessions:
            return sid, self._sessions[sid], False
        sid = sid or secrets.token_urlsafe(16)
        session = self._new_session()
        self._sessions[sid] = session
        return sid, session, True

    def get(self, sid: str | None) -> Session | None:
        return self._sessions.get(sid) if sid else None

    def __len__(self) -> int:
        return len(self._sessions)
