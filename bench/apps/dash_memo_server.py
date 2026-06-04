"""The shared-upstream Dash twin, served by waitress — rival to ``serve_memo.py``.

Sibling of :mod:`bench.apps.dash_server`: same production WSGI server (waitress) and the
same ``GOLIT_BENCH_*`` env contract, but the memoization shape
(:class:`bench.apps.dash_memo.DashMemoTwin`). A ``threshold_a`` move arrives as a
``POST /_dash-update-component`` for ``chart_a.figure``; the callback recomputes the
shared ``heavy`` and returns the bar spec.

    GOLIT_BENCH_ROWS=1000000 GOLIT_BENCH_PORT=8091 python -m bench.apps.dash_memo_server
"""

from __future__ import annotations

import logging
import os

from waitress import serve

from .dash_memo import DashMemoTwin

_ROWS = int(os.environ.get("GOLIT_BENCH_ROWS", "100000"))

application = DashMemoTwin(rows=_ROWS).app.server


def main() -> None:
    port = int(os.environ.get("GOLIT_BENCH_PORT", "8091"))
    logging.getLogger("waitress").setLevel(logging.ERROR)
    serve(application, host="127.0.0.1", port=port, threads=4)


if __name__ == "__main__":
    main()
