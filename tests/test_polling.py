"""Live polled sources: @app.poll registration and the background change-detection loop."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import polars as pl
import pytest
from golit import App
from golit.nodes import NodeKind
from golit.server.polling import _poll_hash, _poll_loop

# -- registration -------------------------------------------------------------


def test_poll_registers_a_source_node_and_a_poller():
    app = App()

    @app.poll("sheet", interval=5)
    async def fetch() -> None:
        return None

    assert "sheet" in app.pollers and app.pollers["sheet"][1] == 5.0
    assert app.node_defs["sheet"].kind is NodeKind.SOURCE  # a real source node was created
    app.poll_cache["sheet"] = "VALUE"
    assert app.node_defs["sheet"].fn() == "VALUE"  # the node reads the cache


def test_poll_rejects_duplicate_name():
    app = App()

    @app.poll("x")
    async def a() -> int:
        return 1

    with pytest.raises(ValueError, match="duplicate"):

        @app.poll("x")
        async def b() -> int:
            return 2


def test_poll_rejects_non_positive_interval():
    app = App()
    with pytest.raises(ValueError, match="positive"):
        app.poll("x", interval=0)


# -- the content hash ---------------------------------------------------------


def test_poll_hash_detects_content_change():
    assert _poll_hash(None) == ""
    same1 = _poll_hash(pl.DataFrame({"a": [1, 2]}))
    same2 = _poll_hash(pl.DataFrame({"a": [1, 2]}))
    diff = _poll_hash(pl.DataFrame({"a": [1, 3]}))
    assert same1 == same2 != diff
    assert _poll_hash(b"abc") == _poll_hash(b"abc") != _poll_hash(b"abd")


# -- the background loop ------------------------------------------------------


async def test_poll_loop_publishes_only_when_data_changes():
    published: list = []
    litestar = SimpleNamespace(
        state=SimpleNamespace(pubsub=SimpleNamespace(publish=lambda inv: _record(published, inv)))
    )
    app = App()
    values = iter(
        [pl.DataFrame({"a": [1]}), pl.DataFrame({"a": [1]}), pl.DataFrame({"a": [2]})]
    )

    async def fetch():
        try:
            return next(values)
        except StopIteration:
            await asyncio.sleep(3600)  # idle after the sequence so the loop stops publishing

    task = asyncio.ensure_future(_poll_loop(litestar, app, "data", fetch, 0.01))
    await asyncio.sleep(0.15)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # value 1 -> publish, value 1 again -> no publish (same hash), value 2 -> publish
    assert len(published) == 2
    assert published[0].node_id == "data" and published[0].session is None
    assert app.poll_cache["data"]["a"].to_list() == [2]  # last good value cached


async def _record(bucket: list, inv) -> None:
    bucket.append(inv)
