"""Input widgets.

A widget is used as the *default value* of a node-function parameter. When Golit
introspects the signature, a parameter whose default is a :class:`Widget` becomes
an **input node** named after the parameter; everything downstream of it re-runs
when its committed value changes.

Each widget knows three things: its default value, how to ``coerce`` a posted
string into the typed Python value, and how to ``render`` its HTML control (wired
for HTMX POST + an Alpine "local shield" for high-frequency feedback).
"""

from __future__ import annotations

import html
import io
from typing import Any


class Widget:
    """Base class for input widgets."""

    kind = "input"

    def __init__(self, *, default: Any = None, label: str | None = None) -> None:
        self.default = default
        self.label = label
        self.name: str | None = None  # bound to the parameter name at registration

    def bind(self, name: str) -> None:
        """Attach this widget to a parameter/input id."""
        self.name = name
        if self.label is None:
            self.label = name.replace("_", " ").title()

    def coerce(self, raw: str) -> Any:
        """Parse a posted form value into the typed Python value."""
        return raw

    def render(self, value: Any) -> str:
        """Render the HTML control showing ``value``."""
        raise NotImplementedError

    # -- helpers -----------------------------------------------------------
    def _label_html(self) -> str:
        return f'<label class="golit-label" for="golit-{esc(self.name)}">{esc(self.label)}</label>'

    def _post_attrs(self, *, trigger: str = "change") -> str:
        return (
            f'hx-post="/node/{esc(self.name)}" hx-trigger="{trigger}" '
            f'hx-swap="none" id="golit-{esc(self.name)}"'
        )


def esc(value: Any) -> str:
    """HTML-escape a value for safe interpolation into markup/attributes."""
    return html.escape(str(value), quote=True)


class Slider(Widget):
    """A numeric range slider. Commits on release (``change``); Alpine shows the
    live value during drag without touching the server."""

    def __init__(
        self,
        low: float,
        high: float,
        *,
        default: float | None = None,
        step: float = 1,
        label: str | None = None,
    ) -> None:
        super().__init__(default=low if default is None else default, label=label)
        self.low = low
        self.high = high
        self.step = step
        self._int = all(float(x).is_integer() for x in (low, high, step, self.default))

    def coerce(self, raw: str) -> float:
        return int(float(raw)) if self._int else float(raw)

    def render(self, value: Any) -> str:
        return (
            f'<div class="golit-widget golit-slider" x-data="{{ v: {esc(value)} }}">'
            f"{self._label_html()} <output x-text=\"v\">{esc(value)}</output>"
            f'<input type="range" name="value" min="{esc(self.low)}" max="{esc(self.high)}" '
            f'step="{esc(self.step)}" value="{esc(value)}" '
            f'x-on:input="v = $event.target.value" {self._post_attrs()}>'
            f"</div>"
        )


class NumberInput(Widget):
    def __init__(
        self,
        low: float | None = None,
        high: float | None = None,
        *,
        default: float = 0,
        step: float = 1,
        label: str | None = None,
    ) -> None:
        super().__init__(default=default, label=label)
        self.low = low
        self.high = high
        self.step = step
        self._int = float(step).is_integer() and float(default).is_integer()

    def coerce(self, raw: str) -> float:
        return int(float(raw)) if self._int else float(raw)

    def render(self, value: Any) -> str:
        bounds = ""
        if self.low is not None:
            bounds += f' min="{esc(self.low)}"'
        if self.high is not None:
            bounds += f' max="{esc(self.high)}"'
        return (
            f'<div class="golit-widget golit-number">{self._label_html()}'
            f'<input type="number" name="value" value="{esc(value)}"'
            f'{bounds} step="{esc(self.step)}" {self._post_attrs()}></div>'
        )


class Select(Widget):
    def __init__(
        self,
        options: list[Any],
        *,
        default: Any = None,
        label: str | None = None,
    ) -> None:
        super().__init__(default=options[0] if default is None else default, label=label)
        self.options = options

    def coerce(self, raw: str) -> Any:
        for opt in self.options:
            if str(opt) == raw:
                return opt
        raise ValueError(f"{raw!r} is not a valid option for {self.name!r}")

    def render(self, value: Any) -> str:
        opts = "".join(
            f'<option value="{esc(o)}"{" selected" if o == value else ""}>{esc(o)}</option>'
            for o in self.options
        )
        return (
            f'<div class="golit-widget golit-select">{self._label_html()}'
            f'<select name="value" {self._post_attrs()}>{opts}</select></div>'
        )


class TextInput(Widget):
    def __init__(
        self,
        *,
        default: str = "",
        label: str | None = None,
        placeholder: str = "",
    ) -> None:
        super().__init__(default=default, label=label)
        self.placeholder = placeholder

    def coerce(self, raw: str) -> str:
        return raw

    def render(self, value: Any) -> str:
        return (
            f'<div class="golit-widget golit-text">{self._label_html()}'
            f'<input type="text" name="value" value="{esc(value)}" '
            f'placeholder="{esc(self.placeholder)}" '
            f'{self._post_attrs(trigger="change, keyup changed delay:400ms")}></div>'
        )


class Checkbox(Widget):
    def __init__(self, *, default: bool = False, label: str | None = None) -> None:
        super().__init__(default=default, label=label)

    def coerce(self, raw: str) -> bool:
        return str(raw).lower() in ("1", "true", "on", "yes")

    def render(self, value: Any) -> str:
        checked = " checked" if value else ""
        # Post an explicit boolean via hx-vals so an unchecked box still commits.
        return (
            f'<div class="golit-widget golit-checkbox">{self._label_html()}'
            f'<input type="checkbox" name="value"{checked} '
            f"hx-vals='js:{{value: event.target.checked}}' {self._post_attrs()}></div>"
        )


class Upload(Widget):
    """A file upload. Coerces the posted bytes into a ``BytesIO`` that Polars
    readers (``pl.read_csv`` etc.) accept directly."""

    def __init__(self, label: str | None = None, *, accept: str | None = None) -> None:
        super().__init__(default=None, label=label)
        self.accept = accept

    def coerce(self, raw: Any) -> io.BytesIO | None:
        if raw is None:
            return None
        if isinstance(raw, (bytes, bytearray)):
            return io.BytesIO(bytes(raw))
        if hasattr(raw, "read"):
            return io.BytesIO(raw.read())
        return io.BytesIO(str(raw).encode())

    def render(self, value: Any) -> str:
        accept = f' accept="{esc(self.accept)}"' if self.accept else ""
        return (
            f'<div class="golit-widget golit-upload">{self._label_html()}'
            f'<input type="file" name="value"{accept} hx-encoding="multipart/form-data" '
            f"{self._post_attrs()}></div>"
        )


# -- ergonomic factory functions (match the project_scope.md examples) --------

def slider(
    low: float,
    high: float,
    *,
    default: float | None = None,
    step: float = 1,
    label: str | None = None,
) -> Slider:
    return Slider(low, high, default=default, step=step, label=label)


def number(
    low: float | None = None,
    high: float | None = None,
    *,
    default: float = 0,
    step: float = 1,
    label: str | None = None,
) -> NumberInput:
    return NumberInput(low, high, default=default, step=step, label=label)


def select(options: list[Any], *, default: Any = None, label: str | None = None) -> Select:
    return Select(options, default=default, label=label)


def text(*, default: str = "", label: str | None = None, placeholder: str = "") -> TextInput:
    return TextInput(default=default, label=label, placeholder=placeholder)


def checkbox(*, default: bool = False, label: str | None = None) -> Checkbox:
    return Checkbox(default=default, label=label)


def upload(label: str | None = None, *, accept: str | None = None) -> Upload:
    return Upload(label, accept=accept)
