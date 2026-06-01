"""Node definitions and signature introspection.

Dependencies are inferred from a function's parameters: a parameter whose default
is a :class:`~golit.widgets.Widget` is an *input* edge; a parameter named after
another registered node is a *dependency* edge; a parameter with a plain default
is a constant.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .widgets import Widget


class NodeKind(StrEnum):
    INPUT = "input"
    SOURCE = "source"
    REACTIVE = "reactive"
    VIEW = "view"


@dataclass(slots=True)
class Param:
    """One parameter of a node function."""

    name: str
    widget: Widget | None  # set when the parameter's default is a Widget
    has_default: bool
    default: Any  # plain (non-widget) default, if any


@dataclass(slots=True)
class NodeDef:
    """The blueprint for a single node (resolved deps filled in by ``App.build``)."""

    id: str
    kind: NodeKind
    fn: Callable[..., Any]
    params: list[Param]
    deps: list[str] = field(default_factory=list)  # upstream ids (inputs + nodes), in param order
    target: str | None = None  # fragment DOM id (views only)


def inspect_params(fn: Callable[..., Any]) -> list[Param]:
    """Extract :class:`Param` metadata from a function signature."""
    params: list[Param] = []
    for name, p in inspect.signature(fn).parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        default = p.default
        if isinstance(default, Widget):
            params.append(Param(name, widget=default, has_default=True, default=None))
        elif default is inspect.Parameter.empty:
            params.append(Param(name, widget=None, has_default=False, default=None))
        else:
            params.append(Param(name, widget=None, has_default=True, default=default))
    return params
