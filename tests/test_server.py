"""Litestar integration: full-page render, and POST returning only the changed
view fragments as out-of-band swaps."""

from __future__ import annotations

import polars as pl
from golit import App, create_app, slider
from golit.server import COOKIE
from litestar.testing import TestClient


def build_app():
    app = App(title="Server Test")

    @app.source
    def data() -> pl.DataFrame:
        return pl.DataFrame({"region": ["N", "S", "E", "W"], "revenue": [10, 40, 25, 80]})

    @app.reactive
    def filtered(data: pl.DataFrame, threshold: int = slider(0, 100, default=20)) -> pl.DataFrame:
        return data.filter(pl.col("revenue") > threshold)

    @app.view
    def chart(filtered: pl.DataFrame) -> str:
        return f"<p>rows={filtered.height}</p>"

    @app.view
    def summary(data: pl.DataFrame) -> str:
        return f"<p>total={data['revenue'].sum()}</p>"

    return create_app(app)


def test_index_renders_full_page_and_sets_cookie():
    with TestClient(app=build_app()) as client:
        r = client.get("/")
        assert r.status_code == 200
        body = r.text
        assert "<title>Server Test</title>" in body
        assert 'id="chart"' in body and 'id="summary"' in body
        assert "rows=3" in body  # threshold=20 → revenue>20 → {40,25,80}
        assert "total=155" in body
        assert COOKIE in r.headers.get("set-cookie", "")


def test_post_returns_only_changed_fragment():
    with TestClient(app=build_app()) as client:
        client.get("/")  # establish session + initial render
        r = client.post("/node/threshold", data={"value": "30"})
        assert r.status_code == 200
        body = r.text
        # Only the chart view changed; it comes back as an OOB swap.
        assert 'id="chart"' in body and 'hx-swap-oob="true"' in body
        assert "rows=2" in body  # revenue>30 → {40,80}
        # summary depends only on data → not in the response.
        assert 'id="summary"' not in body


def test_post_unknown_input_returns_404():
    with TestClient(app=build_app()) as client:
        client.get("/")
        r = client.post("/node/ghost", data={"value": "1"})
        assert r.status_code == 404


def test_create_app_forwards_guards_for_byo_auth():
    """A guard passed to create_app gates every route — the BYO-auth contract."""
    from litestar.connection import ASGIConnection
    from litestar.exceptions import NotAuthorizedException
    from litestar.handlers.base import BaseRouteHandler

    def require_token(connection: ASGIConnection, _handler: BaseRouteHandler) -> None:
        if connection.headers.get("x-token") != "secret":
            raise NotAuthorizedException()

    app = App(title="Guarded")

    @app.view
    def hello() -> str:
        return "<p>hi</p>"

    guarded = create_app(app, guards=[require_token])
    with TestClient(app=guarded) as client:
        assert client.get("/").status_code == 401  # no token → blocked
        assert client.get("/", headers={"x-token": "secret"}).status_code == 200
