"""Page-level layout — ``golit.layout``.

By default Golit stacks every view vertically under one controls panel. A layout
lets you arrange the *reactive view fragments* into columns, tabs, a sidebar, etc.
Crucially, each view stays its own ``<section id=…>``: the layout is just static
scaffold placed around the sections, so the POST out-of-band and SSE swaps still
target each view by id — moving a control re-renders only its fragment, wherever
it sits in the page.

    from golit import layout as L

    app.layout = L.Sidebar(
        L.Controls(),                       # all inputs, in the sidebar
        L.Stack(
            L.Row(L.View("kpi"), L.View("status")),
            L.Tabs({"Chart": L.View("chart"), "Data": L.View("table")}),
        ),
    )

References (``View``/``Control``) point at nodes by id; containers (``Row``,
``Stack``, ``Grid``, ``Tabs``, ``Section``, ``Sidebar``, ``Controls``) nest. A
plain string child is passed through as trusted HTML, so ``golit.ui`` components
drop in as static decoration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .nodes import NodeKind
from .rendering import controls_panel, view_slot
from .ui import card, columns, grid, tabs

if TYPE_CHECKING:
    from .engine import Session

# -- references ---------------------------------------------------------------


class View:
    """Place a view node's fragment (its live ``<section id=…>``)."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id


class Control:
    """Place a single input widget's control."""

    def __init__(self, input_id: str) -> None:
        self.input_id = input_id


class Controls:
    """A panel of input controls — the given ids, or every input if none given."""

    def __init__(self, *input_ids: str) -> None:
        self.input_ids = input_ids


# -- containers ---------------------------------------------------------------


class Row:
    """A responsive row. ``widths`` (summing to 12) gives a custom split."""

    def __init__(self, *children: Any, widths: list[int] | None = None, gap: int = 6) -> None:
        self.children = children
        self.widths = widths
        self.gap = gap


class Stack:
    """A vertical stack with spacing."""

    def __init__(self, *children: Any, gap: int = 8) -> None:
        self.children = children
        self.gap = gap


class Grid:
    """A fixed-column responsive grid."""

    def __init__(self, *children: Any, cols: int = 3, gap: int = 6) -> None:
        self.children = children
        self.cols = cols
        self.gap = gap


class Tabs:
    """A tab group; ``panels`` maps label → child."""

    def __init__(self, panels: dict[str, Any], *, default: str | None = None) -> None:
        self.panels = panels
        self.default = default


class Section:
    """A titled card grouping its children."""

    def __init__(
        self, *children: Any, title: str | None = None, subtitle: str | None = None
    ) -> None:
        self.children = children
        self.title = title
        self.subtitle = subtitle


class Sidebar:
    """A sidebar + main two-column split. ``width`` is the sidebar span (of 12)."""

    def __init__(self, side: Any, main: Any, *, width: int = 4) -> None:
        self.side = side
        self.main = main
        self.width = width


# -- rendering ----------------------------------------------------------------


def render_layout(node: Any, session: Session) -> str:
    """Render a layout tree to HTML, inserting live view sections and controls."""
    if isinstance(node, str):
        return node  # trusted HTML (e.g. a golit.ui component)
    if isinstance(node, View):
        return view_slot(node.node_id, session.fragment(node.node_id) or "")
    if isinstance(node, Control):
        return session.control_html(node.input_id)
    if isinstance(node, Controls):
        ids = node.input_ids or tuple(session.app.widgets)
        return controls_panel([session.control_html(i) for i in ids])
    if isinstance(node, Row):
        kids = [render_layout(c, session) for c in node.children]
        return columns(kids, gap=node.gap, widths=node.widths)
    if isinstance(node, Grid):
        kids = [render_layout(c, session) for c in node.children]
        return grid(kids, cols=node.cols, gap=node.gap)
    if isinstance(node, Stack):
        inner = "".join(render_layout(c, session) for c in node.children)
        return f'<div class="space-y-{node.gap}">{inner}</div>'
    if isinstance(node, Tabs):
        panels = {label: render_layout(child, session) for label, child in node.panels.items()}
        return tabs(panels, default=node.default)
    if isinstance(node, Section):
        kids = [render_layout(c, session) for c in node.children]
        return card(*kids, title=node.title, subtitle=node.subtitle)
    if isinstance(node, Sidebar):
        side = render_layout(node.side, session)
        main = render_layout(node.main, session)
        return (
            '<div class="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">'
            f'<aside class="lg:col-span-{node.width} lg:sticky lg:top-8">{side}</aside>'
            f'<div class="lg:col-span-{12 - node.width}">{main}</div></div>'
        )
    raise TypeError(f"unknown layout node: {node!r}")


# -- validation ---------------------------------------------------------------


def _iter_refs(node: Any) -> Any:
    if isinstance(node, View):
        yield ("view", node.node_id)
    elif isinstance(node, Control):
        yield ("control", node.input_id)
    elif isinstance(node, Controls):
        for cid in node.input_ids:
            yield ("control", cid)
    elif isinstance(node, (Row, Stack, Grid, Section)):
        for child in node.children:
            yield from _iter_refs(child)
    elif isinstance(node, Tabs):
        for child in node.panels.values():
            yield from _iter_refs(child)
    elif isinstance(node, Sidebar):
        yield from _iter_refs(node.side)
        yield from _iter_refs(node.main)


def validate_layout(node: Any, app: Any) -> None:
    """Check every ``View``/``Control`` reference points at a real view/input and
    appears at most once — each is a unique swap target, so a duplicate would put
    two elements with the same id in the DOM and break the by-id swap."""
    seen: set[tuple[str, str]] = set()
    for kind, ref in _iter_refs(node):
        if (kind, ref) in seen:
            label = "View" if kind == "view" else "Control"
            raise ValueError(f"layout: {label}({ref!r}) is placed more than once")
        seen.add((kind, ref))
        if kind == "view":
            ndef = app.node_defs.get(ref)
            if ndef is None:
                raise ValueError(f"layout: View({ref!r}) is not a defined node")
            if ndef.kind is not NodeKind.VIEW:
                raise ValueError(f"layout: View({ref!r}) refers to a {ndef.kind.value}, not a view")
        elif ref not in app.widgets:
            raise ValueError(f"layout: Control({ref!r}) is not a defined input")
