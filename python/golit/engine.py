"""The scheduler driver — one :class:`Session` per client.

On each interaction the engine asks the kernel for the recompute schedule
(``dirty_subgraph``), executes only the nodes whose input signature changed
(memo via ``needs_recompute``), stores fresh values, and returns the view
fragments that actually changed. Nodes left out of the dirty subgraph — or whose
inputs are unchanged — are never executed.

A node's input signature mixes the *content hash* of its scalar input values with
the *epochs* of its upstream nodes: an upstream that recomputed bumped its epoch, so
the signature changes, so this node recomputes — all in O(deps), with no O(rows)
frame hashing. The kernel owns that bookkeeping now: :meth:`Session._run` asks
``graph.check_node`` for each node's ``(kind, needs_recompute, signature)`` in a
single FFI call, then commits the outcome with ``commit_node``/``skip_node``/
``commit_input``. The wire stays minimal independently: a recomputed *view* only
goes out if its rendered fragment string actually differs from the last one sent.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .app import App
from .hashing import hash_value
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
        value = widget.coerce(raw_value)
        self.registry.set(input_id, value)
        # Push the new content hash to the kernel so downstream signatures shift
        # (or, on a revert to a prior value, stay put for a clean memo hit).
        self.graph.commit_input(input_id, hash_value(value))
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
            # One FFI call returns the node's kind, whether its folded input
            # signature changed, and that signature — the kernel did the dep walk.
            kind, needs, sig = self.graph.check_node(node_id)
            if kind == NodeKind.INPUT.value:
                # First sighting: seed the default value and its hash so downstream
                # signatures have something to mix in. Later edits arrive via
                # `update` → `commit_input`.
                if not self.registry.has(node_id):
                    value = self.app.input_default(node_id)
                    self.registry.set(node_id, value)
                    self.graph.commit_input(node_id, hash_value(value))
                continue

            if force or node_id in force_ids or needs:
                value = self._execute(node_id)
                self.registry.set(node_id, value)
                self.graph.commit_node(node_id, sig)  # marks clean, bumps epoch
                if kind == NodeKind.VIEW.value:
                    fragment = self._render(node_id, value)
                    # The body re-ran, but only push it if the bytes on the wire
                    # actually changed — an O(fragment) string compare, never O(rows).
                    if fragment != self.registry.fragment(node_id):
                        self.registry.set_fragment(node_id, fragment)
                        changed[node_id] = fragment
            else:
                # Memo hit: signature unchanged, reuse the stored value without
                # bumping the epoch so nothing downstream sees a phantom change.
                self.graph.skip_node(node_id, sig)
        return changed

    def _execute(self, node_id: str) -> Any:
        ndef = self.app.node_def(node_id)
        kwargs: dict[str, Any] = {}
        for p in ndef.params:
            if p.widget is not None or p.name in self.app.compute_ids:
                kwargs[p.name] = self.registry.get(p.name)
            else:
                kwargs[p.name] = p.default
        return ndef.fn(**kwargs)
