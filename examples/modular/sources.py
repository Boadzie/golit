"""Sources — nodes that bring data *into* the graph.

In a real app these read a file, query a DB, or hit an API. Here it's a small deterministic
frame so the example runs with no inputs or network. Registering happens at import: the
``@app.source`` decorator adds the node to the shared ``app``.
"""

from __future__ import annotations

import polars as pl
from _app import app


@app.source
def sales() -> pl.DataFrame:
    """A tiny fixed sales table — the root of the graph."""
    return pl.DataFrame(
        {
            "region": ["North", "South", "East", "West", "North", "South", "East", "West"],
            "product": ["A", "A", "A", "A", "B", "B", "B", "B"],
            "revenue": [120, 90, 200, 60, 80, 150, 110, 240],
            "units": [12, 9, 20, 6, 8, 15, 11, 24],
        }
    )
