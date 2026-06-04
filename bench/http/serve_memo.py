"""Env-configured Golit ASGI app for the **memoization** HTTP bench.

Sibling of :mod:`bench.http.serve`, but the shared-upstream shape
(:func:`bench.gen_app.make_memo_app`) instead of the single chain: one expensive
``heavy`` node feeds two views. uvicorn imports ``bench.http.serve_memo:application``;
the shared-upstream size comes from ``GOLIT_BENCH_ROWS``. A ``POST /node/threshold_a``
re-renders only ``view_a`` — ``heavy`` stays clean and memoized, which is the whole
point the benchmark measures over real HTTP.
"""

from __future__ import annotations

import os

from golit import create_app

from ..gen_app import make_memo_app

_ROWS = int(os.environ.get("GOLIT_BENCH_ROWS", "100000"))

application = create_app(make_memo_app(rows=_ROWS))
