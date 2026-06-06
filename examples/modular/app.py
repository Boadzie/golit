"""Entrypoint for a Golit app split across modules — run this file.

    golit run examples/modular/app.py

A Golit app is just an ``App`` instance that nodes register on with ``@app.source`` /
``@app.reactive`` / ``@app.view``. Those decorators run at **import time**, so to spread the
nodes across files you only need two things:

1. a single shared ``app`` instance (here, ``_app.py``), imported by every node module; and
2. an entrypoint that **imports every node module** before ``create_app`` — importing is what
   runs the decorators and registers the nodes.

``golit run`` executes this file on its own (not as a package), so it first puts this folder on
``sys.path`` to make the sibling modules importable from any working directory. (For an
installable project, prefer a real package with relative imports, run via
``uvicorn mypkg.main:application`` — see the example's README.)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # make sibling modules importable

import reactives  # noqa: E402,F401  — importing each module registers its @app.* nodes
import sources  # noqa: E402,F401
import views  # noqa: E402,F401
from _app import app  # noqa: E402
from golit import create_app  # noqa: E402

application = create_app(app)
