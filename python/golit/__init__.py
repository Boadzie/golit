"""Golit — a reactive DAG framework for Python.

Streamlit, until it goes to production.
"""

from __future__ import annotations

from golit._golit import kernel_version

from .app import App
from .engine import Session
from .nodes import NodeKind
from .server import create_app
from .widgets import (
    Checkbox,
    NumberInput,
    Select,
    Slider,
    TextInput,
    Upload,
    Widget,
    checkbox,
    number,
    select,
    slider,
    text,
    upload,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "kernel_version",
    "App",
    "Session",
    "create_app",
    "NodeKind",
    "Widget",
    "Slider",
    "NumberInput",
    "Select",
    "TextInput",
    "Checkbox",
    "Upload",
    "slider",
    "number",
    "select",
    "text",
    "checkbox",
    "upload",
]
