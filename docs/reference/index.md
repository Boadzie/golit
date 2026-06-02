# API reference

This reference is generated from the source docstrings, so it tracks the code. For learning Golit, start with the [Tutorial](../tutorial/index.md); come here for exact signatures and behavior.

<div class="golit-grid" markdown>

<div markdown>
### [App & nodes](app.md)
`App`, the node decorators, `NodeKind`, and the per-session `Session`.
</div>

<div markdown>
### [Widgets](widgets.md)
Every input widget and its factory — `slider`, `select`, `upload`, `button`, …
</div>

<div markdown>
### [Charts](charts.md)
`anychart` and the Lets-Plot re-exports.
</div>

<div markdown>
### [UI components](ui.md)
The `golit.ui` presentational builders.
</div>

<div markdown>
### [Layout](layout.md)
The `golit.layout` references and containers.
</div>

<div markdown>
### [SQL / data](data.md)
`golit.sql` and DuckDB relation helpers.
</div>

<div markdown>
### [Server](server.md)
`create_app`, the `PubSub` backends, and `Invalidation`.
</div>

</div>

## Top-level exports

These are importable straight from `golit`:

```python
from golit import (
    App, create_app, Session, NodeKind, sql,
    # widget factories
    slider, number, select, text, textarea, checkbox,
    switch, radio, multiselect, date, upload, button,
)
import golit.ui as ui
from golit import layout as L
```

`golit.kernel_version()` returns the version string of the compiled Rust kernel; `golit.__version__` is the Python package version.
