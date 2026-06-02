"""Env-configured ASGI app for the HTTP harness.

uvicorn imports ``bench.http.serve:application``; the graph shape is read from the
environment so the driver can boot one isolated server process per configuration
(methodology: one framework/config per run, no cross-contamination)::

    GOLIT_BENCH_ROWS        dataset rows         (default 100000)
    GOLIT_BENCH_DEPTH       affected-chain depth (default 3)
    GOLIT_BENCH_UNAFFECTED  unaffected nodes     (default 0)

The app is the *same* synthetic blueprint the in-process B1 uses
(:func:`bench.gen_app.make_app`), so end-to-end numbers are directly comparable
to the engine-only ones.
"""

from __future__ import annotations

import os

from golit import create_app

from ..gen_app import make_app

_ROWS = int(os.environ.get("GOLIT_BENCH_ROWS", "100000"))
_DEPTH = int(os.environ.get("GOLIT_BENCH_DEPTH", "3"))
_UNAFFECTED = int(os.environ.get("GOLIT_BENCH_UNAFFECTED", "0"))

application = create_app(make_app(rows=_ROWS, depth=_DEPTH, unaffected=_UNAFFECTED))
