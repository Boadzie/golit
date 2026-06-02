"""RedisPubSub round-trip and the env-driven backend selector.

A live Redis isn't required: ``fakeredis`` provides an in-process server, and
RedisPubSub accepts an injected client. The publish→listen path proves that an
``Invalidation`` survives JSON serialization across the channel intact, which is
exactly what lets a different worker pick it up in a real fleet.
"""

from __future__ import annotations

import asyncio

import pytest
from fakeredis import aioredis
from golit.server import InMemoryPubSub, RedisPubSub
from golit.server.factory import REDIS_URL_ENV, pubsub_from_env
from golit.server.pubsub import Invalidation


def _pubsub() -> RedisPubSub:
    # One shared in-process server backs both the publisher and the subscriber.
    return RedisPubSub(client=aioredis.FakeRedis())


async def _first(ps: RedisPubSub, inv: Invalidation) -> Invalidation:
    """Subscribe, publish once, and return the single received invalidation."""
    got: list[Invalidation] = []

    async def consume() -> None:
        async for received in ps.listen():
            got.append(received)
            break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)  # let the subscribe land before publishing
    await ps.publish(inv)
    await asyncio.wait_for(task, timeout=2.0)
    return got[0]


async def test_session_scoped_invalidation_round_trips() -> None:
    ps = _pubsub()
    out = await _first(ps, Invalidation("chart", session="s1"))
    assert out == Invalidation("chart", "s1")
    await ps.aclose()


async def test_global_invalidation_round_trips() -> None:
    ps = _pubsub()
    out = await _first(ps, Invalidation("ticker"))  # session=None → every client
    assert out == Invalidation("ticker", None)
    assert out.session is None
    await ps.aclose()


def test_env_selector_defaults_to_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(REDIS_URL_ENV, raising=False)
    assert isinstance(pubsub_from_env(), InMemoryPubSub)


def test_env_selector_picks_redis_when_url_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REDIS_URL_ENV, "redis://localhost:6379/0")
    backend = pubsub_from_env()
    assert isinstance(backend, RedisPubSub)
