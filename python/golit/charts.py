"""User-facing grammar of graphics.

Re-exports Lets-Plot's API so apps can write::

    from golit.charts import ggplot, aes, geom_bar, ggsize

Golit renders the returned spec to a static SVG fragment when its view node is dirty.
"""

from __future__ import annotations

from .rendering.charts import *  # noqa: F401, F403
