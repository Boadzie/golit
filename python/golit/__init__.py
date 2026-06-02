"""Golit — a reactive DAG framework for Python.

Streamlit, until it goes to production.
"""

from __future__ import annotations

from golit._golit import kernel_version

from . import layout, ui
from .app import App
from .data import sql
from .engine import Session
from .nodes import NodeKind
from .server import create_app
from .widgets import (
    Button,
    Checkbox,
    DateInput,
    MultiSelect,
    NumberInput,
    RadioGroup,
    Select,
    Slider,
    Switch,
    TextArea,
    TextInput,
    Upload,
    Widget,
    button,
    checkbox,
    date,
    multiselect,
    number,
    radio,
    select,
    slider,
    switch,
    text,
    textarea,
    upload,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "kernel_version",
    "ui",
    "layout",
    "App",
    "Session",
    "create_app",
    "sql",
    "NodeKind",
    "Widget",
    "Slider",
    "NumberInput",
    "Select",
    "TextInput",
    "Checkbox",
    "Upload",
    "RadioGroup",
    "MultiSelect",
    "Switch",
    "DateInput",
    "TextArea",
    "Button",
    "slider",
    "number",
    "select",
    "text",
    "checkbox",
    "upload",
    "radio",
    "multiselect",
    "switch",
    "date",
    "textarea",
    "button",
]
