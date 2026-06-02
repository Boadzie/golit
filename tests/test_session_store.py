"""Durable session store + cross-worker reconstruction.

A live Redis isn't required: ``fakeredis`` provides an in-process server and
:class:`RedisSessionStore` accepts an injected client. The load-bearing test is
that a *second* worker, which has never seen a session, can rebuild it from the
input state alone — no Polars frames cross Redis, preserving the worker-local
thesis while removing the need for sticky request routing.
"""

from __future__ import annotations

import asyncio

import fakeredis
from golit import App, slider
from golit.server.factory import REDIS_URL_ENV, session_store_from_env
from golit.server.session import SessionManager
from golit.server.session_store import (
    InMemorySessionStore,
    RedisSessionStore,
)


def make_app() -> App:
    app = App(title="t")

    @app.reactive
    def n(threshold: int = slider(0, 100, default=5)) -> int:
        return threshold

    @app.view
    def out(n: int) -> str:
        return f"n={n}"

    return app


def test_inmemory_store_is_a_noop():
    store = InMemorySessionStore()
    assert store.load("anything") is None
    store.save_input("s", "threshold", "9")  # accepted, persists nothing
    assert store.load("s") is None


def test_redis_store_round_trip():
    store = RedisSessionStore(client=fakeredis.FakeStrictRedis())
    assert store.load("s1") is None  # nothing stored yet
    store.save_input("s1", "threshold", "42")
    store.save_input("s1", "other", "x")
    assert store.load("s1") == {"threshold": "42", "other": "x"}
    assert store.load("s2") is None  # isolated per session id


def test_reconstructs_input_state_on_a_fresh_worker():
    # Two workers, two clients, one shared Redis server.
    server = fakeredis.FakeServer()
    store_a = RedisSessionStore(client=fakeredis.FakeStrictRedis(server=server))
    store_b = RedisSessionStore(client=fakeredis.FakeStrictRedis(server=server))
    app = make_app()

    worker_a = SessionManager(app, store=store_a)
    sid, _session, _created, frags = worker_a.prepare_and_update(None, "threshold", "42")
    assert "n=42" in next(iter(frags.values()))  # the change took effect locally

    # A different worker has never seen this sid — it must rebuild from Redis.
    worker_b = SessionManager(app, store=store_b)
    assert worker_b.get(sid) is None  # not in worker B's local cache
    sid2, session, created = worker_b.prepare(sid)
    assert sid2 == sid  # the cookie id is reused, not regenerated
    assert created is False  # reconstructed + rendered, no new cookie
    assert "n=42" in (session.fragment("out") or "")  # input replayed


def test_unknown_input_in_store_is_skipped_on_replay():
    # A stored input id that no longer exists in the graph (app changed between
    # deploys) must not break reconstruction.
    store = RedisSessionStore(client=fakeredis.FakeStrictRedis())
    store.save_input("s1", "threshold", "30")
    store.save_input("s1", "ghost", "999")
    mgr = SessionManager(make_app(), store=store)
    sid, session, created = mgr.prepare("s1")
    assert created is False
    assert "n=30" in (session.fragment("out") or "")  # valid input still applied


def test_session_store_from_env_selects_backend(monkeypatch):
    monkeypatch.delenv(REDIS_URL_ENV, raising=False)
    assert isinstance(session_store_from_env(), InMemorySessionStore)
    monkeypatch.setenv(REDIS_URL_ENV, "redis://localhost:6379")
    store = session_store_from_env()
    assert isinstance(store, RedisSessionStore)  # built lazily, no live connection


def test_lock_for_is_per_session():
    mgr = SessionManager(make_app())
    lock_a = mgr.lock_for("a")
    assert mgr.lock_for("a") is lock_a  # same id -> same lock (serializes the session)
    assert mgr.lock_for("b") is not lock_a  # distinct id -> distinct lock (parallel)
    assert isinstance(lock_a, asyncio.Lock)
    # An anonymous request (no cookie yet) gets a throwaway, uncontended lock.
    assert mgr.lock_for(None) is not mgr.lock_for(None)
