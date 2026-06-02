"""DuckDB integration: golit.sql(), relation rendering, and memo hashing."""

from __future__ import annotations

import polars as pl
import pytest
from golit import App, create_app, slider, sql
from golit.data import is_duckdb_relation, relation_to_polars
from golit.hashing import hash_value
from golit.rendering import render_value
from litestar.testing import TestClient

duckdb = pytest.importorskip("duckdb")


def test_sql_runs_over_named_frames_and_returns_polars():
    df = pl.DataFrame({"region": ["N", "N", "S"], "revenue": [10, 20, 30]})
    out = sql(
        "SELECT region, sum(revenue)::BIGINT AS revenue "
        "FROM data GROUP BY region ORDER BY region",
        data=df,
    )
    assert isinstance(out, pl.DataFrame)
    assert out.to_dicts() == [
        {"region": "N", "revenue": 30},
        {"region": "S", "revenue": 30},
    ]


def test_relation_detected_and_rendered_as_table():
    rel = duckdb.sql("SELECT 1 AS a, 'x' AS b")
    assert is_duckdb_relation(rel)
    assert isinstance(relation_to_polars(rel), pl.DataFrame)
    out = render_value(rel)
    assert "golit-table" in out and ">a<" in out


def test_relation_hash_is_content_based():
    a = duckdb.sql("SELECT * FROM range(3) t(i)")
    b = duckdb.sql("SELECT * FROM range(3) t(i)")
    c = duckdb.sql("SELECT * FROM range(4) t(i)")
    assert hash_value(a) == hash_value(b)  # same data → memo hit
    assert hash_value(a) != hash_value(c)


def test_sql_node_in_app_renders_and_swaps():
    app = App(title="SQL")

    @app.source
    def data() -> pl.DataFrame:
        return pl.DataFrame({"region": ["N", "N", "S", "S"], "revenue": [10, 20, 30, 40]})

    @app.reactive
    def agg(data: pl.DataFrame, threshold: int = slider(0, 100, default=0)) -> pl.DataFrame:
        return sql(
            "SELECT region, sum(revenue)::BIGINT AS revenue FROM d "
            f"WHERE revenue > {int(threshold)} GROUP BY region ORDER BY region",
            d=data,
        )

    @app.view
    def table(agg: pl.DataFrame) -> pl.DataFrame:
        return agg

    application = create_app(app)
    with TestClient(app=application) as client:
        r = client.get("/")
        assert "golit-table" in r.text and "N" in r.text
        r2 = client.post("/node/threshold", data={"value": "25"}, cookies=r.cookies)
        assert 'id="table"' in r2.text and "hx-swap-oob" in r2.text
