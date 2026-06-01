"""Lets-Plot integration.

Re-exports the grammar of graphics (``ggplot``, ``aes``, ``geom_*``, ``ggsize``,
…) so view nodes can build plots, and converts a plot spec to a static SVG string
server-side — no client-side charting runtime, just markup an HTMX swap handles
like any other fragment.
"""

from __future__ import annotations

from typing import Any

from lets_plot import *  # noqa: F401, F403  (re-export the grammar of graphics)
from lets_plot import LetsPlot

_setup_done = False


def _ensure_setup() -> None:
    """Put Lets-Plot in static, no-JavaScript mode (idempotent)."""
    global _setup_done
    if not _setup_done:
        LetsPlot.setup_html(no_js=True)
        _setup_done = True


def is_plot(value: Any) -> bool:
    """Whether ``value`` is a Lets-Plot spec we should render to SVG."""
    module = type(value).__module__ or ""
    return module.startswith("lets_plot") and callable(getattr(value, "to_svg", None))


def plot_to_svg(plot: Any) -> str:
    """Render a Lets-Plot spec to a standalone SVG string."""
    _ensure_setup()
    svg = plot.to_svg()
    return svg.decode("utf-8") if isinstance(svg, bytes) else svg
