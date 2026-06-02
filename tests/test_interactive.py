"""Interactive-chart adapters: Plotly/Altair/Bokeh detection, the AnyChart helper,
the mount fragment, and the page-shell bootstrap.

Plotly/Altair detection keys off the value's ``__module__``, so lightweight fakes
exercise it without importing those heavy libraries. Bokeh's path imports its
serializer, so that test is skipped unless Bokeh is actually installed.
"""

from __future__ import annotations

import html
import json

import polars as pl
import pytest
from golit.charts import anychart
from golit.rendering import render_value
from golit.rendering.html import page


class _FakePlotlyFigure:
    __module__ = "plotly.graph_objs._figure"

    def to_json(self) -> str:
        return '{"data": [{"type": "bar", "x": ["N"], "y": [1]}], "layout": {"title": "t"}}'


class _FakeAltairChart:
    __module__ = "altair.vegalite.v5.api"

    def to_json(self) -> str:
        return '{"$schema": "https://vega.github.io/schema/vega-lite/v5.json", "mark": "bar"}'


def _spec_of(fragment: str) -> dict:
    """Pull the JSON spec back out of a mount's data-chart-spec attribute."""
    marker = 'data-chart-spec="'
    start = fragment.index(marker) + len(marker)
    end = fragment.index('"', start)
    return json.loads(html.unescape(fragment[start:end]))


def test_plotly_figure_renders_as_plotly_mount() -> None:
    out = render_value(_FakePlotlyFigure())
    assert 'class="golit-chart' in out
    assert 'data-chart-lib="plotly"' in out
    assert _spec_of(out)["data"][0]["type"] == "bar"


def test_altair_chart_renders_as_vega_mount() -> None:
    out = render_value(_FakeAltairChart())
    assert 'data-chart-lib="vega"' in out
    assert _spec_of(out)["mark"] == "bar"


def test_anychart_from_dataframe() -> None:
    df = pl.DataFrame({"region": ["North", "South"], "revenue": [120, 200]})
    out = anychart(df, "region", "revenue", kind="bar", title="Revenue")
    assert 'data-chart-lib="anychart"' in out
    spec = _spec_of(out)
    assert spec["kind"] == "bar"
    assert spec["title"] == "Revenue"
    assert spec["data"] == [["North", 120], ["South", 200]]


def test_anychart_from_rows() -> None:
    out = anychart([["A", 1], ["B", 2]], kind="pie")
    spec = _spec_of(out)
    assert spec["kind"] == "pie"
    assert spec["data"] == [["A", 1], ["B", 2]]


def test_anychart_dataframe_requires_columns() -> None:
    df = pl.DataFrame({"region": ["North"], "revenue": [1]})
    with pytest.raises(ValueError):
        anychart(df)


def test_mount_spec_is_html_escaped() -> None:
    # The JSON's quotes must be entity-escaped so the attribute stays well-formed.
    out = anychart([["A", 1]])
    assert "&quot;" in out
    assert 'data-chart-spec=""' not in out


def test_plain_values_do_not_become_mounts() -> None:
    assert "golit-chart" not in render_value(42)
    assert "golit-chart" not in render_value(pl.DataFrame({"a": [1]}))  # → table


def test_page_shell_carries_chart_bootstrap() -> None:
    shell = page("Gallery", "<main></main>")
    assert "golitInitCharts" in shell
    assert "GOLIT_CHART_CDN" in shell
    assert "cdn.plot.ly" in shell  # plotly CDN wired into the config


def test_bokeh_figure_renders_as_bokeh_mount() -> None:
    pytest.importorskip("bokeh")
    from bokeh.plotting import figure

    fig = figure(width=320, height=240, title="b")
    fig.vbar(x=[1, 2, 3], top=[4, 2, 5], width=0.8)
    out = render_value(fig)
    assert 'data-chart-lib="bokeh"' in out
    assert "data-chart-version=" in out  # BokehJS pinned to the installed Bokeh
    assert _spec_of(out)  # valid JSON item


def test_plotly_express_figure_renders_as_plotly_mount() -> None:
    pytest.importorskip("plotly")
    import plotly.express as px

    # px returns a plotly.graph_objs Figure and takes a Polars frame directly.
    df = pl.DataFrame({"region": ["North", "South"], "revenue": [120, 200]})
    out = render_value(px.bar(df, x="region", y="revenue"))
    assert 'data-chart-lib="plotly"' in out
    assert _spec_of(out)["data"][0]["type"] == "bar"
