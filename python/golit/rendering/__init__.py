"""Rendering layer: view values → HTML fragments, plus the page shell."""

from __future__ import annotations

from .html import controls_panel, oob_fragment, page, view_slot
from .protocol import Renderer, render_value

__all__ = [
    "render_value",
    "Renderer",
    "page",
    "view_slot",
    "oob_fragment",
    "controls_panel",
]
