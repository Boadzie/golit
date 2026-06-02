"""User-facing charting API.

Re-exports Lets-Plot's grammar of graphics (static SVG), plus :func:`anychart` for
an AnyChart mount, so apps can write::

    from golit.charts import ggplot, aes, geom_bar, ggsize   # static SVG
    from golit.charts import anychart                        # interactive JS

Plotly, Altair, and Bokeh figures need no helper — return one from a view and
Golit renders it to an interactive client-side chart (see rendering/interactive.py).
"""

from __future__ import annotations

from .rendering.charts import *  # noqa: F401, F403
from .rendering.interactive import anychart  # noqa: F401
