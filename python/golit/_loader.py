"""Worker entry point for multi-process ``golit run --workers N``.

uvicorn's ``--workers`` spawns subprocesses, each of which must *import* the ASGI
app by string — but a Golit app lives in an arbitrary user file, not an importable
module. ``golit run`` bridges that by storing the resolved file path in
``GOLIT_APP_PATH`` and pointing uvicorn at ``golit._loader:application``; every
worker imports this module and rebuilds the same app from that path.
"""

from __future__ import annotations

import os
from pathlib import Path

from .cli import _load_application

_path = os.environ.get("GOLIT_APP_PATH")
if not _path:  # pragma: no cover - only hit on misuse outside `golit run`
    raise RuntimeError("GOLIT_APP_PATH is not set; launch with `golit run`")

application = _load_application(Path(_path))
