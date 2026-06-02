"""Env-configured Dash app, served by waitress — the rival to Golit's ``serve.py``.

Dash is a Flask (WSGI) app; ``twin.app.server`` is that Flask object. To compare
Dash's *real* per-update HTTP path against Golit's (which runs under uvicorn, a
production ASGI server), we serve Dash under **waitress**, a production WSGI server,
on its own loopback port — not the Werkzeug dev server. The graph shape comes from the
same ``GOLIT_BENCH_*`` env the Golit harness uses, so one isolated process serves one
configuration::

    GOLIT_BENCH_ROWS / _DEPTH / _UNAFFECTED   graph shape (defaults 100000 / 3 / 0)
    GOLIT_BENCH_PORT                          loopback port to bind

A slider move reaches this server as a ``POST /_dash-update-component`` (see
:func:`bench.http.drive.measure_dash_http`); Flask routes it, sets up
``callback_context``, runs the callback (chain + build the Plotly figure), and returns
the figure as JSON — the full server-side work the direct-call floor skips.

    GOLIT_BENCH_PORT=890 python -m bench.apps.dash_server
"""

from __future__ import annotations

import logging
import os

from waitress import serve

from .dash_app import DashTwin

_ROWS = int(os.environ.get("GOLIT_BENCH_ROWS", "100000"))
_DEPTH = int(os.environ.get("GOLIT_BENCH_DEPTH", "3"))
_UNAFFECTED = int(os.environ.get("GOLIT_BENCH_UNAFFECTED", "0"))

# The Flask WSGI app Dash builds; waitress serves it.
application = DashTwin(rows=_ROWS, depth=_DEPTH, unaffected=_UNAFFECTED).app.server


def main() -> None:
    port = int(os.environ.get("GOLIT_BENCH_PORT", "8090"))
    logging.getLogger("waitress").setLevel(logging.ERROR)
    serve(application, host="127.0.0.1", port=port, threads=4)


if __name__ == "__main__":
    main()
