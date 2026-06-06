"""Great Tables: a view returning a ``GT`` object is auto-detected and rendered as its
self-contained HTML. Skipped when the optional ``great_tables`` dependency is absent."""

from __future__ import annotations

import polars as pl
import pytest
from golit.rendering import render_value

pytest.importorskip("great_tables")
from great_tables import GT  # noqa: E402


def test_gt_object_renders_as_self_contained_html():
    gt = GT(pl.DataFrame({"item": ["A", "B"], "price": [12.5, 9.0]})).tab_header("Demo")
    out = render_value(gt)
    assert "golit-great-table" in out  # wrapped in the golit surface
    assert "gt_table" in out and "<style" in out  # GT's own markup + scoped styles
    assert "Demo" in out  # the header rendered
    assert "<script" not in out  # no JS dependency — renders statically


def test_gt_takes_priority_over_generic_repr_html():
    # GT also exposes _repr_html_, but the explicit branch owns it (consistent wrapper).
    out = render_value(GT(pl.DataFrame({"x": [1]})))
    assert out.startswith('<div class="golit-great-table')


def test_view_returning_gt_renders_in_the_page():
    from golit import App, create_app
    from litestar.testing import TestClient

    app = App(title="GT")

    @app.view
    def report() -> GT:
        return GT(pl.DataFrame({"region": ["N", "S"], "rev": [100, 200]})).tab_header("Report")

    with TestClient(app=create_app(app)) as client:
        body = client.get("/").text
    assert "golit-great-table" in body and "gt_table" in body and "Report" in body
