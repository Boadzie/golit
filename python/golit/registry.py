"""Per-session value store.

The kernel holds topology + per-node state/hash; the registry holds the actual
*values*. Because a clean node keeps its stored value untouched, the registry is
itself the memo cache — a memo hit simply means "leave ``values[id]`` as is".
"""

from __future__ import annotations

from typing import Any


class Registry:
    """Current node values and rendered view fragments for one session."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.fragments: dict[str, str] = {}

    def has(self, node_id: str) -> bool:
        return node_id in self.values

    def get(self, node_id: str) -> Any:
        return self.values[node_id]

    def get_or(self, node_id: str, default: Any = None) -> Any:
        return self.values.get(node_id, default)

    def set(self, node_id: str, value: Any) -> None:
        self.values[node_id] = value

    def set_fragment(self, node_id: str, html: str) -> None:
        self.fragments[node_id] = html

    def fragment(self, node_id: str) -> str | None:
        return self.fragments.get(node_id)
