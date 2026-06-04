"""Dash twin for the memoization benchmark: a shared upstream the callback recomputes.

Mirror of :class:`bench.apps.dash_app.DashTwin`, but the shared-upstream shape: two
sliders, two charts, one expensive ``heavy`` step both charts build on. Each chart has
its own callback with a single ``Input`` (its slider) — exactly what a Dash dev writes —
so a slider move re-runs that callback's whole body, recomputing ``heavy(data)`` every
time. Dash has no cross-callback memo, so the work Golit skips, Dash repeats.

Both engines run the *same* ``memo_heavy``/``memo_payload`` (from
:mod:`bench.gen_app`) and both return a **raw dict** figure — so the only thing this
benchmark isolates is recompute-vs-memoize, not the chart-object trick. The callback
returning a plain dict means even an already-optimized Dash is the rival here.
"""

from __future__ import annotations

from dash import Dash, Input, Output, dcc, html

from ..gen_app import _make_frame, memo_heavy, memo_payload


class DashMemoTwin:
    """An idiomatic shared-upstream Dash app; ``app.server`` is the Flask WSGI object."""

    def __init__(self, *, rows: int) -> None:
        self.data = _make_frame(rows)
        self.app = Dash(__name__)
        self.app.layout = html.Div(
            [
                dcc.Slider(0, 100, value=10, id="threshold_a"),
                dcc.Graph(id="chart_a"),
                dcc.Slider(0, 100, value=10, id="threshold_b"),
                dcc.Graph(id="chart_b"),
            ]
        )

        @self.app.callback(Output("chart_a", "figure"), Input("threshold_a", "value"))
        def update_a(threshold_a: int) -> dict:
            # Idiomatic Dash: the callback body recomputes the shared upstream every move.
            return memo_payload(memo_heavy(self.data), threshold_a)

        @self.app.callback(Output("chart_b", "figure"), Input("threshold_b", "value"))
        def update_b(threshold_b: int) -> dict:
            return memo_payload(memo_heavy(self.data), threshold_b)

        self._update_a = update_a
