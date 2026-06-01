"""The scheduler driver — one :class:`Session` per client.

On each interaction the engine asks the kernel for the recompute schedule
(``dirty_subgraph``), executes only the nodes whose input signature changed
(memo via ``needs_recompute``), stores fresh values, and returns the view
fragments that actually changed. Nodes left out of the dirty subgraph — or whose
inputs hashed identically — are never executed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .app import App
from .hashing import signature_hash
from .nodes import NodeKind
from .registry import Registry

ViewRenderer = Callable[[str, Any], str]


def _default_renderer(node_id: str, value: Any) -> str:
    return f'<div id="{node_id}">{value}</div>'


class Session:
    """Per-session reactive state: a fresh kernel graph + value registry built
    from the shared :class:`App` blueprint."""

    def __init__(self, app: App, *, view_renderer: ViewRenderer | None = None) -> None:
        self.app = app
        self.graph = app.new_graph()
        self.registry = Registry()
        self._render = view_renderer or _default_renderer

    # -- public API --------------------------------------------------------
    def initial_render(self) -> dict[str, str]:
        """Compute the whole graph once; return every view fragment."""
        return self._run(self.graph.topo_order(), force=True)

    def update(self, input_id: str, raw_value: Any) -> dict[str, str]:
        """Commit an input change and return only the view fragments that changed."""
        widget = self.app.widget_for(input_id)
        if widget is None:
            raise KeyError(f"unknown input {input_id!r}")
        self.registry.set(input_id, widget.coerce(raw_value))
        return self._run(self.graph.dirty_subgraph([input_id]))

    def refresh(self, node_id: str) -> dict[str, str]:
        """Force-recompute a node (e.g. a streaming source or a shared node) and
        everything downstream; return the view fragments that changed. This is the
        server-initiated path that feeds the SSE push channel."""
        return self._run(self.graph.dirty_subgraph([node_id]), force_ids={node_id})

    def control_html(self, input_id: str) -> str:
        """Render an input's HTML control at its current value."""
        widget = self.app.widget_for(input_id)
        assert widget is not None
        return widget.render(self.registry.get_or(input_id, widget.default))

    def fragment(self, node_id: str) -> str | None:
        return self.registry.fragment(node_id)

    # -- internals ---------------------------------------------------------
    def _run(
        self, schedule: list[str], *, force: bool = False, force_ids: set[str] | None = None
    ) -> dict[str, str]:
        force_ids = force_ids or set()
        changed: dict[str, str] = {}
        for node_id in schedule:
            kind = self.graph.kind_of(node_id)
            if kind == NodeKind.INPUT.value:
                if not self.registry.has(node_id):
                    self.registry.set(node_id, self.app.input_default(node_id))
                self.graph.set_clean(node_id, signature_hash([self.registry.get(node_id)]))
                continue

            sig = self._input_signature(node_id)
            if force or node_id in force_ids or self.graph.needs_recompute(node_id, sig):
                self.graph.set_computing(node_id)
                value = self._execute(node_id)
                self.registry.set(node_id, value)
                self.graph.set_clean(node_id, sig)
                if kind == NodeKind.VIEW.value:
                    fragment = self._render(node_id, value)
                    self.registry.set_fragment(node_id, fragment)
                    changed[node_id] = fragment
            else:
                # Memo hit: inputs hashed identically, reuse the stored value.
                self.graph.set_clean(node_id, sig)
        return changed

    def _input_signature(self, node_id: str) -> int:
        return signature_hash([self.registry.get(dep) for dep in self.graph.deps_of(node_id)])

    def _execute(self, node_id: str) -> Any:
        ndef = self.app.node_def(node_id)
        kwargs: dict[str, Any] = {}
        for p in ndef.params:
            if p.widget is not None or p.name in self.app.compute_ids:
                kwargs[p.name] = self.registry.get(p.name)
            else:
                kwargs[p.name] = p.default
        return ndef.fn(**kwargs)
