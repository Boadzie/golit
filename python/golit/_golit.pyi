"""Type stubs for the Rust kernel extension `golit._golit`.

The implementation lives in `src/core.rs` (logic) and `src/lib.rs` (PyO3 bindings).
"""

from __future__ import annotations

def kernel_version() -> str:
    """Version of the compiled Rust kernel."""

class Graph:
    """Reactive DAG: dirty tracking, topological scheduling, propagation, memo.

    Holds topology and per-node state/hash only — node values stay Python-side.
    Lifecycle: ``add_node``/``set_deps`` to declare, ``build`` to validate and
    cache the topological order, then the query methods on every interaction.
    """

    def __init__(self) -> None: ...
    def add_node(self, id: str, kind: str) -> None:
        """Register a node. ``kind`` is one of input|source|reactive|view."""

    def set_deps(self, id: str, deps: list[str]) -> None:
        """Set a node's dependencies (all must already be registered)."""

    def build(self) -> None:
        """Validate acyclicity and cache the topological order."""

    def topo_order(self) -> list[str]:
        """All node ids, topologically sorted."""

    def dirty_subgraph(self, seeds: list[str]) -> list[str]:
        """Recompute schedule: seeds + transitive dependents, topo-ordered."""

    def mark_dirty(self, seeds: list[str]) -> list[str]:
        """Mark seeds and downstream dirty; return them topo-ordered."""

    def downstream(self, id: str) -> list[str]:
        """Nodes strictly downstream of ``id``, topo-ordered."""

    def needs_recompute(self, id: str, input_hash: int) -> bool:
        """Whether ``id`` needs recompute given the hash of its current inputs."""

    def set_clean(self, id: str, hash: int) -> None:
        """Commit ``id`` clean with the content hash it was computed from."""

    def check_node(self, id: str) -> tuple[str, bool, int]:
        """Hot-path per-node decision: ``(kind, needs_recompute, signature)`` in one
        call. Folds the node's dependency signature (Input deps by content hash,
        computed deps by epoch) and the memo check entirely in Rust."""

    def commit_node(self, id: str, signature: int) -> None:
        """Commit a computed node clean with the signature it ran on; bumps its epoch."""

    def skip_node(self, id: str, signature: int) -> None:
        """Commit a memo hit clean without bumping the epoch."""

    def commit_input(self, id: str, content_hash: int) -> None:
        """Record an Input node's current value hash for downstream signatures."""

    def set_computing(self, id: str) -> None: ...
    def set_dirty(self, id: str) -> None: ...
    def state_of(self, id: str) -> str: ...
    def kind_of(self, id: str) -> str: ...
    def deps_of(self, id: str) -> list[str]: ...
    def dirty_nodes(self) -> list[str]: ...
    def views(self) -> list[str]: ...
    def node_ids(self) -> list[str]: ...
    def __len__(self) -> int: ...
    def __contains__(self, id: str) -> bool: ...
