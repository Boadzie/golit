"""Rendering layer: value → fragment dispatch, Lets-Plot SVG, page shell."""

from __future__ import annotations

import polars as pl
from golit.rendering import oob_fragment, page, render_value, view_slot


def test_str_is_trusted_markup():
    assert render_value("<b>hi</b>") == "<b>hi</b>"


def test_none_is_empty():
    assert render_value(None) == ""


def test_fallback_escapes_repr():
    out = render_value(1234)
    assert "golit-value" in out and "1234" in out


def test_dataframe_renders_table():
    df = pl.DataFrame({"region": ["N", "S"], "revenue": [10, 40]})
    out = render_value(df)
    assert "golit-table" in out
    assert "<th>region</th>" in out and "<th>revenue</th>" in out
    assert "<td>40</td>" in out


def test_custom_renderer_protocol():
    class Badge:
        def __golit_render__(self) -> str:
            return "<span class='badge'>ok</span>"

    assert render_value(Badge()) == "<span class='badge'>ok</span>"


def test_letsplot_spec_becomes_svg():
    from golit.charts import aes, geom_bar, ggplot, ggsize

    df = pl.DataFrame({"region": ["N", "S", "E"], "revenue": [10, 40, 25]})
    plot = ggplot(df, aes("region", "revenue")) + geom_bar(stat="identity") + ggsize(320, 200)
    out = render_value(plot)
    assert "golit-chart" in out
    assert "<svg" in out.lower()


def test_view_slot_and_oob_fragment():
    slot = view_slot("chart", "X")
    assert 'id="chart"' in slot and 'sse-swap="node:chart"' in slot

    oob = oob_fragment("chart", "X")
    assert 'id="chart"' in oob and 'hx-swap-oob="true"' in oob


def test_page_shell_includes_scripts_and_title():
    out = page("Sales Explorer", "<div>body</div>")
    assert "<title>Sales Explorer</title>" in out
    assert "htmx.org" in out and "alpinejs" in out
    assert "<div>body</div>" in out
