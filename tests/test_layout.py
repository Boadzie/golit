"""Page-level layout: rendering, swap-target invariants, and validation."""

from __future__ import annotations

import golit.ui as ui
import polars as pl
import pytest
from golit import App, create_app, slider
from golit import layout as L
from golit.engine import Session
from golit.layout import render_layout
from golit.rendering import render_value
from litestar.testing import TestClient


def _app() -> App:
    app = App(title="Layout")

    @app.source
    def data() -> pl.DataFrame:
        return pl.DataFrame({"region": ["N", "S"], "revenue": [1, 2]})

    @app.reactive
    def filtered(data: pl.DataFrame, threshold: int = slider(0, 10, default=1)) -> pl.DataFrame:
        return data.filter(pl.col("revenue") > threshold)

    @app.view
    def kpi(filtered: pl.DataFrame) -> str:
        return ui.metric("Rows", str(filtered.height))

    @app.view
    def table(filtered: pl.DataFrame) -> pl.DataFrame:
        return filtered

    @app.view
    def chart(filtered: pl.DataFrame) -> str:
        return "<svg/>"

    return app


def _session(app: App) -> Session:
    sess = Session(app, view_renderer=lambda _id, v: render_value(v))
    sess.initial_render()
    return sess


def test_layout_places_sections_and_preserves_swap_targets():
    app = _app()
    app.layout = L.Sidebar(
        L.Controls(),
        L.Stack(
            L.Row(L.View("kpi"), L.View("chart")),
            L.Tabs({"Data": L.View("table")}, default="Data"),
        ),
    )
    app.build()
    html = render_layout(app.layout, _session(app))
    # every view keeps its id and SSE swap target, wherever it sits
    for vid in ("kpi", "chart", "table"):
        assert f'id="{vid}"' in html
        assert f'sse-swap="node:{vid}"' in html
    assert "golit-controls" in html  # controls panel
    assert "golit-tabs" in html
    assert "lg:col-span-4" in html  # sidebar width


def test_str_children_pass_through_as_html():
    app = _app()
    app.build()
    html = render_layout(L.Stack(ui.divider(label="X"), L.View("kpi")), _session(app))
    assert "X" in html and 'id="kpi"' in html


def test_controls_subset_and_single_control():
    app = _app()
    app.build()
    sess = _session(app)
    one = render_layout(L.Control("threshold"), sess)
    assert 'name="value"' in one and "golit-controls" not in one  # bare control


def test_grid_and_section_containers():
    app = _app()
    app.build()
    html = render_layout(
        L.Section(L.Grid(L.View("kpi"), L.View("table"), cols=2), title="Panel"),
        _session(app),
    )
    assert "Panel" in html and "lg:grid-cols-2" in html


def test_validation_rejects_unknown_view():
    app = _app()
    app.layout = L.View("nope")
    with pytest.raises(ValueError, match="not a defined node"):
        app.build()


def test_validation_rejects_non_view_reference():
    app = _app()
    app.layout = L.View("filtered")  # a reactive node, not a view
    with pytest.raises(ValueError, match="not a view"):
        app.build()


def test_validation_rejects_unknown_control():
    app = _app()
    app.layout = L.Controls("ghost")
    with pytest.raises(ValueError, match="not a defined input"):
        app.build()


def test_validation_rejects_duplicate_placement():
    app = _app()
    app.layout = L.Stack(L.View("kpi"), L.Row(L.View("kpi")))
    with pytest.raises(ValueError, match="more than once"):
        app.build()


def test_no_layout_falls_back_to_default():
    app = _app()  # layout is None
    application = create_app(app)
    with TestClient(app=application) as client:
        body = client.get("/").text
        assert "golit-controls" in body
        for vid in ("kpi", "table", "chart"):
            assert f'id="{vid}"' in body


def test_layout_post_swap_targets_section_in_scaffold():
    app = _app()
    app.layout = L.Sidebar(L.Controls(), L.Stack(L.View("kpi"), L.View("table")))
    application = create_app(app)
    with TestClient(app=application) as client:
        r = client.get("/")
        assert 'id="kpi"' in r.text  # placed inside the sidebar scaffold
        r2 = client.post("/node/threshold", data={"value": "5"}, cookies=r.cookies)
        # the OOB fragment still targets the view by id
        assert 'id="kpi"' in r2.text and "hx-swap-oob" in r2.text
