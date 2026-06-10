"""Rendering layer: view values → HTML fragments, plus the page shell."""

from __future__ import annotations

from .html import controls_panel, oob_fragment, page, view_slot
from .interactive import anychart, chart_spec, try_interactive
from .protocol import Renderer, escape, render_value

__all__ = [
    "render_value",
    "escape",
    "Renderer",
    "anychart",
    "chart_spec",
    "try_interactive",
    "page",
    "view_slot",
    "oob_fragment",
    "controls_panel",
]
