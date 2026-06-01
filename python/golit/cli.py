"""Golit command-line entry point: ``golit run <app.py>``.

Loads a Python file and launches it under uvicorn. The file may expose either a
Litestar ``application`` (e.g. ``application = create_app(app)``) or a bare Golit
``app`` (an :class:`App`), which is wrapped with ``create_app`` automatically.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any


def _load_application(path: Path) -> Any:
    from litestar import Litestar

    from .app import App
    from .server import create_app

    spec = importlib.util.spec_from_file_location("golit_user_app", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"golit: cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    members = list(vars(module).values())
    for value in members:
        if isinstance(value, Litestar):
            return value
    for value in members:
        if isinstance(value, App):
            return create_app(value)
    raise SystemExit(f"golit: no Litestar `application` or golit `App` found in {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="golit", description="A reactive DAG framework for Python."
    )
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="Run a Golit app under uvicorn")
    run.add_argument("path", help="Path to the app module (e.g. examples/sales_explorer/app.py)")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    if args.command != "run":
        parser.print_help()
        return 1

    import uvicorn

    application = _load_application(Path(args.path).resolve())
    print(f"golit: serving {args.path} at http://{args.host}:{args.port}")
    uvicorn.run(application, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
