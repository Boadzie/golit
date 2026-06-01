"""Build a Litestar ASGI app from a Golit :class:`App`."""

from __future__ import annotations

from litestar import Litestar
from litestar.datastructures import State

from ..app import App
from .routes import index, update_node
from .session import SessionManager


def create_app(app: App) -> Litestar:
    """Wire a Golit blueprint into a runnable Litestar application."""
    app.build()
    manager = SessionManager(app)
    return Litestar(
        route_handlers=[index, update_node],
        state=State({"sessions": manager}),
    )
