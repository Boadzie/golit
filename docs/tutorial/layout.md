# Page layout

By default Golit stacks every view vertically under one controls panel. That's fine to start, but real dashboards want sidebars, rows, and tabs. `golit.layout` lets you arrange the reactive view fragments into a page.

```python
from golit import layout as L
```

## The default (no layout)

With `app.layout` unset, Golit renders a controls panel (every input) above a vertical stack of every view. You don't have to do anything for this.

## Setting a layout

Assign a tree of layout nodes to `app.layout`:

```python
from golit import layout as L

app.layout = L.Sidebar(
    L.Controls(),                                  # all inputs, in the sidebar
    L.Stack(
        L.Row(L.View("kpi"), L.View("status")),
        L.Tabs({"Chart": L.View("chart"), "Data": L.View("table")}),
    ),
)
```

## The crucial property: layout is *static scaffold*

This is what makes it safe. A layout doesn't wrap your views in anything reactive — each `View` still renders as its own `<section id="…">`. The layout is just markup placed *around* those sections.

So the POST out-of-band swaps and SSE pushes still target each view **by id**, wherever it sits in the page. Moving a control re-renders only its fragment, in place — exactly as it does without a layout. You get arrangement without giving up selective recompute.

## References

References point at nodes by id:

| Reference | Places |
| --- | --- |
| `View(node_id)` | A view node's live fragment (its `<section id=…>`). |
| `Control(input_id)` | A single input widget's control. |
| `Controls(*input_ids)` | A panel of controls — the given ids, or **every** input if none given. |

## Containers

Containers nest to build structure:

| Container | Shape |
| --- | --- |
| `Row(*children, widths=None, gap=6)` | A responsive row; `widths` (summing to 12) gives a custom split. |
| `Stack(*children, gap=8)` | A vertical stack with spacing. |
| `Grid(*children, cols=3, gap=6)` | A fixed-column responsive grid. |
| `Tabs(panels, default=None)` | A tab group; `panels` maps label → child. |
| `Section(*children, title=None, subtitle=None)` | A titled card grouping its children. |
| `Sidebar(side, main, width=4)` | A sidebar + main two-column split; `width` is the sidebar span (of 12). |

A plain **string** child is passed through as trusted HTML, so a `golit.ui` component drops in as static decoration:

```python
import golit.ui as ui

app.layout = L.Stack(
    ui.heading("Sales dashboard"),                 # static decoration
    L.Row(L.View("kpi"), L.View("status")),
)
```

## References are validated at build time

When the app builds, Golit checks the whole layout tree:

- Every `View`/`Control` must resolve to a **real** view/input.
- A `View` must point at a node that's actually a `view` (not a source/reactive).
- Each `View`/`Control` may appear **at most once**.

!!! warning "Why 'at most once'"
    Each view is a unique swap target keyed by its DOM id. Placing the same `View("chart")` twice would put two elements with the same id in the page and break by-id swaps — so Golit rejects it with a clear error instead of letting it fail mysteriously at runtime.

The [`components_gallery`](https://github.com/boadzie/golit/tree/main/examples/components_gallery) example uses a `Sidebar` + `Stack` + `Tabs` layout end to end.

## Next

**[SQL nodes](sql.md)** — write a reactive node as DuckDB SQL over your frames.
