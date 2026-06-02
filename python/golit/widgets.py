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

import datetime
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
        return (
            '<label class="text-xs font-semibold uppercase tracking-wider text-on-surface-variant" '
            f'for="golit-{esc(self.name)}">{esc(self.label)}</label>'
        )

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
            f'<div class="golit-widget flex flex-col gap-2" x-data="{{ v: {esc(value)} }}">'
            f'<div class="flex items-center justify-between">{self._label_html()}'
            '<output class="font-mono text-sm text-primary bg-primary-fixed px-2.5 py-0.5 '
            f'rounded-full" x-text="v">{esc(value)}</output></div>'
            f'<input type="range" name="value" min="{esc(self.low)}" max="{esc(self.high)}" '
            f'step="{esc(self.step)}" value="{esc(value)}" '
            'class="w-full accent-primary-container cursor-pointer" '
            f'x-on:input="v = $event.target.value" {self._post_attrs()}>'
            "</div>"
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
            f'<div class="golit-widget flex flex-col gap-2">{self._label_html()}'
            f'<input type="number" name="value" value="{esc(value)}"{bounds} '
            f'step="{esc(self.step)}" class="bg-surface-container-highest border-none rounded-lg '
            'px-3 py-2 text-sm font-body text-on-surface focus:ring-2 focus:ring-primary" '
            f"{self._post_attrs()}></div>"
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
            f'<div class="golit-widget flex flex-col gap-2">{self._label_html()}'
            '<select name="value" class="bg-surface-container-highest border-none rounded-lg '
            'px-3 py-2 text-sm font-body text-on-surface focus:ring-2 focus:ring-primary" '
            f"{self._post_attrs()}>{opts}</select></div>"
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
            f'<div class="golit-widget flex flex-col gap-2">{self._label_html()}'
            f'<input type="text" name="value" value="{esc(value)}" '
            f'placeholder="{esc(self.placeholder)}" '
            'class="bg-surface-container-highest border-none rounded-lg px-3 py-2 text-sm '
            'font-body text-on-surface focus:ring-2 focus:ring-primary" '
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
            '<div class="golit-widget flex items-center gap-3 py-2">'
            f'<input type="checkbox" name="value"{checked} '
            'class="w-4 h-4 accent-primary-container rounded cursor-pointer" '
            f"hx-vals='js:{{value: event.target.checked}}' {self._post_attrs()}>"
            f"{self._label_html()}</div>"
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
            f'<div class="golit-widget flex flex-col gap-2">{self._label_html()}'
            f'<input type="file" name="value"{accept} hx-encoding="multipart/form-data" '
            'class="text-sm text-on-surface-variant file:mr-3 file:py-2 file:px-4 file:rounded-lg '
            'file:border-0 file:bg-primary file:text-on-primary file:font-semibold '
            f'file:cursor-pointer hover:file:opacity-90" {self._post_attrs()}></div>'
        )


class RadioGroup(Widget):
    """A single choice from a set, shown as radio buttons. Each radio posts its own
    value on ``change`` (no shared id), coerced back to the original option object."""

    def __init__(
        self, options: list[Any], *, default: Any = None, label: str | None = None
    ) -> None:
        super().__init__(default=options[0] if default is None else default, label=label)
        self.options = options

    def coerce(self, raw: str) -> Any:
        for opt in self.options:
            if str(opt) == raw:
                return opt
        raise ValueError(f"{raw!r} is not a valid option for {self.name!r}")

    def render(self, value: Any) -> str:
        post = (
            f'hx-post="/node/{esc(self.name)}" hx-trigger="change" hx-swap="none"'
        )
        items = "".join(
            '<label class="flex items-center gap-2 text-sm cursor-pointer">'
            f'<input type="radio" name="value" value="{esc(o)}"'
            f'{" checked" if o == value else ""} '
            f'class="accent-primary-container w-4 h-4" {post}>'
            f"<span>{esc(o)}</span></label>"
            for o in self.options
        )
        return (
            f'<div class="golit-widget flex flex-col gap-2">{self._label_html()}'
            f'<div class="flex flex-col gap-1.5">{items}</div></div>'
        )


class MultiSelect(Widget):
    """Zero or more choices, as a checkbox group. A request-time ``hx-vals`` script
    reads the checked boxes and posts them comma-joined, so the single-``value``
    POST contract is preserved; ``coerce`` splits and maps back to option objects."""

    def __init__(
        self,
        options: list[Any],
        *,
        default: list[Any] | tuple[Any, ...] = (),
        label: str | None = None,
    ) -> None:
        super().__init__(default=list(default), label=label)
        self.options = options

    def coerce(self, raw: str) -> list[Any]:
        chosen = set(raw.split(",")) if raw else set()
        return [opt for opt in self.options if str(opt) in chosen]

    def render(self, value: Any) -> str:
        selected = {str(v) for v in (value or [])}
        boxes = "".join(
            '<label class="flex items-center gap-2 text-sm cursor-pointer">'
            f'<input type="checkbox" data-val="{esc(o)}"'
            f'{" checked" if str(o) in selected else ""} '
            'class="accent-primary-container w-4 h-4">'
            f"<span>{esc(o)}</span></label>"
            for o in self.options
        )
        vals = (
            "js:{value: Array.from(this.querySelectorAll('input[type=checkbox]:checked'))"
            ".map(function(e){return e.dataset.val;}).join(',')}"
        )
        return (
            f'<div class="golit-widget flex flex-col gap-2" hx-post="/node/{esc(self.name)}" '
            f"hx-trigger=\"change\" hx-swap=\"none\" hx-vals='{vals}' "
            f'id="golit-{esc(self.name)}">{self._label_html()}'
            f'<div class="flex flex-col gap-1.5">{boxes}</div></div>'
        )


class Switch(Widget):
    """A boolean toggle (styled checkbox). Posts ``true``/``false`` via ``hx-vals``
    so an off-state still commits."""

    def __init__(self, label: str | None = None, *, default: bool = False) -> None:
        super().__init__(default=default, label=label)

    def coerce(self, raw: str) -> bool:
        return str(raw).lower() in ("1", "true", "on", "yes")

    def render(self, value: Any) -> str:
        checked = " checked" if value else ""
        return (
            '<div class="golit-widget flex items-center justify-between gap-3 py-1">'
            f"{self._label_html()}"
            '<label class="relative inline-flex items-center cursor-pointer">'
            f'<input type="checkbox"{checked} class="sr-only peer" '
            f"hx-vals='js:{{value: event.target.checked}}' {self._post_attrs()}>"
            '<div class="w-10 h-6 bg-surface-container-highest rounded-full '
            'peer-checked:bg-primary-container transition-colors"></div>'
            '<div class="absolute left-1 w-4 h-4 bg-white rounded-full shadow transition-transform '
            'peer-checked:translate-x-4"></div></label></div>'
        )


class DateInput(Widget):
    """A native date picker. Coerces the ISO string to ``datetime.date`` (or ``None``)."""

    def __init__(
        self, *, default: datetime.date | None = None, label: str | None = None
    ) -> None:
        super().__init__(default=default, label=label)

    def coerce(self, raw: str) -> datetime.date | None:
        return datetime.date.fromisoformat(raw) if raw else None

    def render(self, value: Any) -> str:
        if isinstance(value, datetime.date):
            iso = value.isoformat()
        else:
            iso = str(value) if value else ""
        return (
            f'<div class="golit-widget flex flex-col gap-2">{self._label_html()}'
            f'<input type="date" name="value" value="{esc(iso)}" '
            'class="bg-surface-container-highest border-none rounded-lg px-3 py-2 text-sm '
            'font-body text-on-surface focus:ring-2 focus:ring-primary" '
            f"{self._post_attrs()}></div>"
        )


class TextArea(Widget):
    """A multi-line text input. Commits on blur or after a short typing pause."""

    def __init__(
        self,
        *,
        default: str = "",
        label: str | None = None,
        placeholder: str = "",
        rows: int = 4,
    ) -> None:
        super().__init__(default=default, label=label)
        self.placeholder = placeholder
        self.rows = rows

    def coerce(self, raw: str) -> str:
        return raw

    def render(self, value: Any) -> str:
        return (
            f'<div class="golit-widget flex flex-col gap-2">{self._label_html()}'
            f'<textarea name="value" rows="{esc(self.rows)}" '
            f'placeholder="{esc(self.placeholder)}" '
            'class="bg-surface-container-highest border-none rounded-lg px-3 py-2 text-sm '
            'font-body text-on-surface focus:ring-2 focus:ring-primary resize-y" '
            f'{self._post_attrs(trigger="change, keyup changed delay:400ms")}>'
            f"{esc(value)}</textarea></div>"
        )


class Button(Widget):
    """An action trigger. Each click posts a fresh nonce (``Date.now()``), so the
    input's value changes and the dirty subgraph re-runs — the reactive equivalent
    of "on click". The value itself is a monotonic counter a node can ignore."""

    _STYLES = {
        "primary": "bg-primary text-on-primary hover:opacity-90",
        "secondary": "bg-surface-container-high text-on-surface hover:bg-surface-container-highest",
        "ghost": "text-primary hover:bg-primary-fixed/40",
    }

    def __init__(self, label: str | None = None, *, kind: str = "primary") -> None:
        super().__init__(default=0, label=label)
        self.style = kind

    def coerce(self, raw: str) -> int:
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return 0

    def render(self, value: Any) -> str:
        cls = self._STYLES.get(self.style, self._STYLES["primary"])
        return (
            '<div class="golit-widget flex flex-col gap-2 justify-end">'
            f'<button type="button" class="{cls} rounded-lg px-4 py-2 text-sm font-semibold '
            'transition-all w-full" '
            f"hx-vals='js:{{value: Date.now()}}' {self._post_attrs(trigger='click')}>"
            f"{esc(self.label)}</button></div>"
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


def radio(options: list[Any], *, default: Any = None, label: str | None = None) -> RadioGroup:
    return RadioGroup(options, default=default, label=label)


def multiselect(
    options: list[Any],
    *,
    default: list[Any] | tuple[Any, ...] = (),
    label: str | None = None,
) -> MultiSelect:
    return MultiSelect(options, default=default, label=label)


def switch(label: str | None = None, *, default: bool = False) -> Switch:
    return Switch(label, default=default)


def date(*, default: datetime.date | None = None, label: str | None = None) -> DateInput:
    return DateInput(default=default, label=label)


def textarea(
    *,
    default: str = "",
    label: str | None = None,
    placeholder: str = "",
    rows: int = 4,
) -> TextArea:
    return TextArea(default=default, label=label, placeholder=placeholder, rows=rows)


def button(label: str | None = None, *, kind: str = "primary") -> Button:
    return Button(label, kind=kind)
