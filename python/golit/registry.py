"""Per-session value store.

The kernel holds topology + per-node state/hash; the registry holds the actual
*values*. Because a clean node keeps its stored value untouched, the registry is
itself the memo cache — a memo hit simply means "leave ``values[id]`` as is".

It also stamps every stored value with a monotonically increasing **epoch**. A
node's epoch changes iff its value was (re)written, so a downstream node can decide
whether to recompute by comparing its dependencies' epochs against the ones it last
saw — an O(1) check, instead of content-hashing (e.g. ``DataFrame.hash_rows``, which
is O(rows) and, for cheap-to-recompute nodes, costs more than the recompute it
guards). The clock is process-monotonic and never reused, so it has none of the
``id()``-recycling hazards of identity-based schemes. See
:meth:`golit.engine.Session._input_signature`.
"""

from __future__ import annotations

from typing import Any


class Registry:
    """Current node values and rendered view fragments for one session."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.fragments: dict[str, str] = {}
        self._epochs: dict[str, int] = {}
        self._clock = 0

    def has(self, node_id: str) -> bool:
        return node_id in self.values

    def get(self, node_id: str) -> Any:
        return self.values[node_id]

    def get_or(self, node_id: str, default: Any = None) -> Any:
        return self.values.get(node_id, default)

    def set(self, node_id: str, value: Any) -> None:
        self.values[node_id] = value
        self._clock += 1
        self._epochs[node_id] = self._clock

    def epoch(self, node_id: str) -> int:
        """Version stamp of ``node_id``'s current value (0 if never set)."""
        return self._epochs.get(node_id, 0)

    def set_fragment(self, node_id: str, html: str) -> None:
        self.fragments[node_id] = html

    def fragment(self, node_id: str) -> str | None:
        return self.fragments.get(node_id)
