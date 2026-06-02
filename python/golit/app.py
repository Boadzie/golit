"""The :class:`App` blueprint.

An ``App`` collects node definitions from the ``@app.source`` / ``@app.reactive``
/ ``@app.view`` decorators and resolves the dependency graph. It is an immutable
*blueprint*: each client session instantiates its own kernel :class:`Graph` and
:class:`~golit.registry.Registry` from it (state is per-session; topology is shared).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from golit._golit import Graph

from .nodes import NodeDef, NodeKind, inspect_params
from .widgets import Widget

NodeFn = Callable[..., Any]


class App:
    def __init__(self, title: str = "Golit App") -> None:
        self.title = title
        self._defs: dict[str, NodeDef] = {}
        self._order: list[str] = []
        self._widgets: dict[str, Widget] = {}
        self._built = False
        #: Optional page layout tree (see :mod:`golit.layout`); ``None`` stacks
        #: every view under one controls panel.
        self.layout: Any = None

    # -- registration ------------------------------------------------------
    def _register(self, fn: NodeFn, kind: NodeKind) -> NodeFn:
        node_id = fn.__name__
        if node_id in self._defs:
            raise ValueError(f"duplicate node {node_id!r}")
        params = inspect_params(fn)
        self._defs[node_id] = NodeDef(id=node_id, kind=kind, fn=fn, params=params)
        self._order.append(node_id)
        for p in params:
            if p.widget is not None:
                p.widget.bind(p.name)
                self._widgets.setdefault(p.name, p.widget)
        self._built = False
        return fn

    def source(self, fn: NodeFn) -> NodeFn:
        """Register a **source** node (brings data in — read a file, query a DB,
        return a sample frame). May depend on inputs. Returns ``fn`` unchanged."""
        return self._register(fn, NodeKind.SOURCE)

    def reactive(self, fn: NodeFn) -> NodeFn:
        """Register a **reactive** node — a pure transform over its upstream nodes
        and inputs. Re-runs only when one of those changes. Returns ``fn`` unchanged."""
        return self._register(fn, NodeKind.REACTIVE)

    def view(self, fn: NodeFn) -> NodeFn:
        """Register a **view** node — a renderable leaf whose return value Golit
        turns into a UI fragment. Re-renders only when an input changes. Returns
        ``fn`` unchanged."""
        return self._register(fn, NodeKind.VIEW)

    # -- resolution --------------------------------------------------------
    def build(self) -> None:
        """Resolve every parameter to an input/dependency/constant. Raises if a
        parameter is neither a widget, a known node, nor a defaulted constant."""
        for node_id, ndef in self._defs.items():
            deps: list[str] = []
            for p in ndef.params:
                if p.widget is not None:
                    deps.append(p.name)  # edge to the input node
                elif p.name in self._defs:
                    deps.append(p.name)  # edge to another compute node
                elif p.has_default:
                    continue  # constant kwarg
                else:
                    raise ValueError(
                        f"node {node_id!r}: parameter {p.name!r} is not a known node "
                        f"or widget input (and has no default)"
                    )
            ndef.deps = deps
            if ndef.kind is NodeKind.VIEW:
                ndef.target = node_id
        if self.layout is not None:
            from .layout import validate_layout

            validate_layout(self.layout, self)
        self._built = True

    def new_graph(self) -> Graph:
        """Build a fresh kernel graph for a session (topology only; state is
        reset per session)."""
        if not self._built:
            self.build()
        graph = Graph()
        for input_id in self._widgets:
            graph.add_node(input_id, NodeKind.INPUT.value)
        for node_id, ndef in self._defs.items():
            graph.add_node(node_id, ndef.kind.value)
        for node_id, ndef in self._defs.items():
            if ndef.deps:
                graph.set_deps(node_id, ndef.deps)
        graph.build()
        return graph

    # -- introspection -----------------------------------------------------
    @property
    def compute_ids(self) -> set[str]:
        return set(self._defs)

    @property
    def node_defs(self) -> dict[str, NodeDef]:
        return self._defs

    @property
    def widgets(self) -> dict[str, Widget]:
        return self._widgets

    def node_def(self, node_id: str) -> NodeDef:
        return self._defs[node_id]

    def widget_for(self, input_id: str) -> Widget | None:
        return self._widgets.get(input_id)

    def input_default(self, input_id: str) -> Any:
        return self._widgets[input_id].default
