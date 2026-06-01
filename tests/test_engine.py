"""Engine + kernel integration: dependency inference, memoization, and the
"cost ∝ change" guarantee — only the affected nodes execute, and only changed
view fragments come back."""

from __future__ import annotations

import polars as pl
import pytest
from golit import App, Session, slider


def _identity(node_id: str, value: object) -> object:
    """View renderer that passes the computed value straight through, so tests
    assert on values rather than HTML wrapping."""
    return value


def make_session(app: App) -> Session:
    return Session(app, view_renderer=_identity)


def make_app() -> tuple[App, dict[str, int]]:
    """The canonical sales-explorer graph, instrumented with per-node call counts."""
    calls = {"data": 0, "filtered": 0, "chart": 0, "summary": 0}
    app = App(title="test")

    @app.source
    def data() -> pl.DataFrame:
        calls["data"] += 1
        return pl.DataFrame(
            {"region": ["N", "S", "E", "W"], "revenue": [10, 40, 25, 80]}
        )

    @app.reactive
    def filtered(data: pl.DataFrame, threshold: int = slider(0, 100, default=20)) -> pl.DataFrame:
        calls["filtered"] += 1
        return data.filter(pl.col("revenue") > threshold)

    @app.view
    def chart(filtered: pl.DataFrame) -> str:
        calls["chart"] += 1
        return f"rows={filtered.height}"

    @app.view
    def summary(data: pl.DataFrame) -> str:
        # Depends only on `data`, NOT on threshold — must never re-run on slider moves.
        calls["summary"] += 1
        return f"total={data['revenue'].sum()}"

    return app, calls


def test_dependency_inference():
    app, _ = make_app()
    app.build()
    assert app.node_def("filtered").deps == ["data", "threshold"]
    assert app.node_def("chart").deps == ["filtered"]
    assert app.node_def("summary").deps == ["data"]
    assert "threshold" in app.widgets  # widget param became an input node


def test_initial_render_runs_every_node_once():
    app, calls = make_app()
    session = make_session(app)
    fragments = session.initial_render()
    assert calls == {"data": 1, "filtered": 1, "chart": 1, "summary": 1}
    assert set(fragments) == {"chart", "summary"}  # both views rendered
    assert fragments["chart"] == "rows=3"  # revenue > 20 → {40, 25, 80}


def test_slider_recomputes_only_affected_subgraph():
    app, calls = make_app()
    session = make_session(app)
    session.initial_render()
    base = dict(calls)

    changed = session.update("threshold", "30")

    # data and summary are NOT downstream of threshold → never re-executed.
    assert calls["data"] == base["data"]
    assert calls["summary"] == base["summary"]
    # filtered + chart recompute.
    assert calls["filtered"] == base["filtered"] + 1
    assert calls["chart"] == base["chart"] + 1
    # Only the chart fragment is returned (summary unaffected).
    assert set(changed) == {"chart"}
    assert changed["chart"] == "rows=2"  # revenue > 30 → {40, 80}


def test_memo_hit_when_output_unchanged():
    """Lowering the threshold from 20 to 5 still yields the same filtered rows
    (all revenues > 5 and > 20 differ here) — pick a no-op change to prove the
    chart memo-hits when `filtered` is unchanged."""
    app, calls = make_app()
    session = make_session(app)
    session.initial_render()  # threshold=20 → rows {40,25,80}? revenue>20 → 40,25,80 = 3
    assert session.fragment("chart") == "rows=3"
    base = dict(calls)

    # threshold 20 -> 21: still revenue>21 keeps {40,25,80} (25>21) → filtered identical.
    changed = session.update("threshold", "21")
    assert calls["filtered"] == base["filtered"] + 1  # filtered re-runs (input changed)
    assert calls["chart"] == base["chart"]  # but chart memo-hits (filtered unchanged)
    assert changed == {}  # nothing actually changed on the wire


def test_unknown_input_rejected():
    app, _ = make_app()
    session = make_session(app)
    session.initial_render()
    with pytest.raises(KeyError):
        session.update("nonexistent", "1")


def test_unresolved_parameter_raises_at_build():
    app = App()

    @app.reactive
    def broken(missing_dep):  # not a node, not a widget, no default
        return missing_dep

    with pytest.raises(ValueError, match="not a known node"):
        app.build()
