"""User-facing charting API.

Re-exports Lets-Plot's grammar of graphics (static SVG), plus :func:`anychart` for
an AnyChart mount, so apps can write::

    from golit.charts import ggplot, aes, geom_bar, ggsize   # static SVG
    from golit.charts import anychart, chart_spec            # interactive JS

Plotly, Altair, and Bokeh figures need no helper — return one from a view and
Golit renders it to an interactive client-side chart (see rendering/interactive.py).
For a hot view that rebuilds its chart every interaction, :func:`chart_spec` ships the
raw spec dict directly, skipping the heavy figure object (much faster + lighter).
"""

from __future__ import annotations

from .rendering.charts import *  # noqa: F401, F403
from .rendering.interactive import anychart, chart_spec  # noqa: F401
