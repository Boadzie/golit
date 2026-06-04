"""DuckDB integration — SQL nodes over Polars frames.

DuckDB is in-process and exchanges data with Polars zero-copy, so a node can run
SQL over its upstream frames and hand a Polars frame downstream — memoized and
rendered like any other frame. Use :func:`sql` for an eager SQL node:

    from golit import sql

    @app.reactive
    def by_region(data):                      # `data` is an upstream Polars frame
        return sql(
            "SELECT region, sum(revenue) AS revenue "
            "FROM data GROUP BY region ORDER BY region",
            data=data,
        )

Raw ``duckdb.sql(...)`` relations returned from a node also work: Golit detects a
``DuckDBPyRelation`` and materializes it to Polars for rendering and hashing.
DuckDB is an optional dependency (``pip install "golit[sql]"``); it is imported
only inside :func:`sql`, never at framework import time.
"""

from __future__ import annotations

import threading
from typing import Any

import polars as pl

# One DuckDB connection per worker thread, reused across `sql()` calls. Opening a
# connection per query is wasted setup on the hot path; a thread-local keeps it
# cheap while staying safe (a DuckDB connection is not meant to be shared across
# threads concurrently).
_local = threading.local()


def _connection() -> Any:
    con = getattr(_local, "con", None)
    if con is None:
        import duckdb

        con = duckdb.connect()  # in-process, in-memory
        _local.con = con
        _local.loaded = set()  # extensions loaded on this connection (see load_extension)
    return con


def load_extension(name: str) -> None:
    """Install and load a DuckDB extension on this thread's connection, once.

    DuckDB downloads an extension on first ``INSTALL`` (e.g. ``spatial`` for ``ST_*``
    functions); we track what's already loaded per connection so repeated calls on the
    hot path are a no-op. Used by :func:`golit.gis.spatial_sql`."""
    con = _connection()
    loaded = _local.loaded
    if name in loaded:
        return
    con.install_extension(name)
    con.load_extension(name)
    loaded.add(name)


def is_duckdb_relation(value: Any) -> bool:
    """Whether ``value`` is a ``DuckDBPyRelation`` (without importing duckdb).

    The class lives in the ``_duckdb`` pybind11 module on current builds (and
    ``duckdb`` on older ones), so match either by substring."""
    cls = type(value)
    return cls.__name__ == "DuckDBPyRelation" and "duckdb" in (cls.__module__ or "")


def relation_to_polars(relation: Any) -> pl.DataFrame:
    """Materialize a DuckDB relation to a Polars ``DataFrame``."""
    to_pl = getattr(relation, "pl", None)
    if callable(to_pl):
        return to_pl()
    return pl.from_arrow(relation.arrow())  # type: ignore[return-value]


def sql(query: str, **frames: Any) -> pl.DataFrame:
    """Run a DuckDB SQL ``query`` over the given named frames, returning Polars.

    Each keyword binds a name usable in the query (``sql("… FROM data", data=df)``);
    values may be Polars/pandas/Arrow frames. The result is fully materialized, so
    it memoizes and renders exactly like a Polars node output."""
    con = _connection()  # reused per thread
    try:
        for name, frame in frames.items():
            con.register(name, frame)
        return con.sql(query).pl()  # fully materialized before the views are dropped
    finally:
        # Unbind this call's frames so they don't leak or collide with the next
        # query on the same (reused) connection.
        for name in frames:
            con.unregister(name)
