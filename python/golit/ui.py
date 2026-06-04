"""Presentational components — ``golit.ui``.

Unlike widgets (reactive *inputs*), these are pure builders a view returns: they
take renderables and produce shadcn-styled, server-rendered HTML that slots into
the fragment pipeline. Any argument is run through :func:`render_value`, so you can
nest a DataFrame, a chart figure, another component, or trusted HTML uniformly::

    import golit.ui as ui

    @app.view
    def panel(by_region, total):
        return ui.card(
            ui.columns([ui.metric("Revenue", f"${total:,}", delta="+8%"), chart_fig]),
            title="Overview",
        )

Layout (card/columns/grid/tabs/expander/accordion/divider), display
(metric/scorecard/alert/badge/progress/skeleton/spinner), and rich data
(table/markdown/code/json_view/heading/caption).
"""

from __future__ import annotations

import json
import re
from typing import Any

from .rendering import render_value
from .widgets import esc

__all__ = [
    "card",
    "columns",
    "grid",
    "tabs",
    "expander",
    "accordion",
    "divider",
    "metric",
    "scorecard",
    "alert",
    "badge",
    "progress",
    "skeleton",
    "spinner",
    "table",
    "markdown",
    "code",
    "json_view",
    "heading",
    "caption",
    "chat",
]


def _join(items: Any) -> str:
    return "".join(render_value(i) for i in items)


# -- layout & containers ------------------------------------------------------

def card(
    *body: Any,
    title: str | None = None,
    subtitle: str | None = None,
    footer: Any = None,
) -> str:
    """A surface card with optional title/subtitle/footer."""
    head = ""
    if title or subtitle:
        head = '<div class="mb-4">'
        if title:
            head += f'<h3 class="font-headline text-lg font-bold tracking-tight">{esc(title)}</h3>'
        if subtitle:
            head += f'<p class="text-sm text-on-surface-variant mt-0.5">{esc(subtitle)}</p>'
        head += "</div>"
    foot = ""
    if footer is not None:
        foot = (
            '<div class="mt-4 pt-4 border-t border-outline-variant/20 text-sm '
            f'text-on-surface-variant">{render_value(footer)}</div>'
        )
    return (
        '<div class="golit-card bg-surface-container-low rounded-xl p-6 shadow-sm">'
        f"{head}{_join(body)}{foot}</div>"
    )


def columns(items: list[Any], *, gap: int = 6, widths: list[int] | None = None) -> str:
    """Lay renderables out in a responsive row. ``widths`` (summing to 12) gives a
    custom split; otherwise the columns are equal and stack on small screens."""
    if widths is not None:
        cells = "".join(
            f'<div class="col-span-12 md:col-span-{w}">{render_value(it)}</div>'
            for it, w in zip(items, widths, strict=True)
        )
        return f'<div class="grid grid-cols-12 gap-{gap}">{cells}</div>'
    n = max(1, len(items))
    cells = "".join(f"<div>{render_value(it)}</div>" for it in items)
    return f'<div class="grid grid-cols-1 md:grid-cols-{n} gap-{gap}">{cells}</div>'


def grid(items: list[Any], *, cols: int = 3, gap: int = 6) -> str:
    """A fixed-column responsive grid (1 → 2 → ``cols`` across breakpoints)."""
    cells = "".join(f"<div>{render_value(it)}</div>" for it in items)
    return (
        f'<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-{cols} gap-{gap}">{cells}</div>'
    )


def tabs(panels: dict[str, Any], *, default: str | None = None) -> str:
    """A client-side tab group (Alpine). ``panels`` maps label → renderable."""
    labels = list(panels)
    start = labels.index(default) if default in labels else 0
    active = "text-primary border-primary"
    inactive = "text-on-surface-variant border-transparent hover:text-on-surface"
    bar = "".join(
        f'<button type="button" x-on:click="tab={i}" '
        f""":class="tab==={i} ? '{active}' : '{inactive}'" """
        'class="px-4 py-2 text-sm font-semibold border-b-2 transition-colors">'
        f"{esc(label)}</button>"
        for i, label in enumerate(labels)
    )
    bodies = "".join(
        f'<div x-show="tab==={i}" x-cloak>{render_value(content)}</div>'
        for i, content in enumerate(panels.values())
    )
    return (
        f'<div class="golit-tabs" x-data="{{ tab: {start} }}">'
        f'<div class="flex gap-1 border-b border-outline-variant/30 mb-4">{bar}</div>'
        f"<div>{bodies}</div></div>"
    )


def expander(title: str, *body: Any, open: bool = False) -> str:
    """A collapsible section (native ``<details>`` — no JS needed)."""
    op = " open" if open else ""
    return (
        f'<details class="golit-expander bg-surface-container-low rounded-xl px-5"{op}>'
        '<summary class="flex items-center justify-between cursor-pointer py-4 font-semibold '
        f'text-sm">{esc(title)}'
        '<span class="material-symbols-outlined golit-chev text-on-surface-variant">'
        "expand_more</span></summary>"
        f'<div class="pb-4 text-sm">{_join(body)}</div></details>'
    )


def accordion(sections: dict[str, Any]) -> str:
    """A stack of independently collapsible sections."""
    return (
        '<div class="golit-accordion flex flex-col gap-2">'
        + "".join(expander(title, body) for title, body in sections.items())
        + "</div>"
    )


def divider(*, label: str | None = None) -> str:
    """A horizontal rule, optionally with a centered label."""
    if label:
        return (
            '<div class="flex items-center gap-3 my-6">'
            '<div class="h-px bg-outline-variant/30 flex-1"></div>'
            '<span class="text-xs uppercase tracking-widest text-on-surface-variant">'
            f"{esc(label)}</span>"
            '<div class="h-px bg-outline-variant/30 flex-1"></div></div>'
        )
    return '<hr class="border-0 h-px bg-outline-variant/30 my-6">'


# -- display & status ---------------------------------------------------------

def _delta_html(delta: Any, delta_color: str) -> str:
    """An up/down delta pill (green good / red bad), shared by :func:`metric` and
    :func:`scorecard`. ``delta_color`` is ``normal`` (up=good), ``inverse`` (down=good), or
    ``off`` (neutral); a leading ``-`` marks a downward delta."""
    if delta is None:
        return ""
    ds = str(delta).strip()
    down = ds.startswith("-")
    if delta_color == "off":
        color = "text-on-surface-variant"
    else:
        good = down if delta_color == "inverse" else not down
        color = "text-green-600" if good else "text-red-600"
    arrow = "▼" if down else "▲"
    return (
        f'<span class="inline-flex items-center gap-0.5 text-sm font-semibold {color}">'
        f"{arrow} {esc(ds.lstrip('+-'))}</span>"
    )


def metric(
    label: str,
    value: Any,
    *,
    delta: Any = None,
    delta_color: str = "normal",
    help: str | None = None,
) -> str:
    """A KPI: big value, label, and an optional up/down delta. ``delta_color`` is
    ``normal`` (up=good/green), ``inverse`` (down=good), or ``off`` (neutral)."""
    help_html = ""
    if help:
        help_html = (
            '<span class="material-symbols-outlined text-sm text-outline cursor-help" '
            f'title="{esc(help)}">help</span>'
        )
    return (
        '<div class="golit-metric">'
        '<div class="flex items-center gap-1 text-xs font-bold uppercase tracking-widest '
        f'text-on-surface-variant">{esc(label)}{help_html}</div>'
        '<div class="flex items-baseline gap-2 mt-1">'
        f'<span class="font-headline text-3xl font-bold tracking-tight">{esc(value)}</span>'
        f"{_delta_html(delta, delta_color)}</div></div>"
    )


_SCORECARD_ACCENT = {
    "default": ("bg-surface-container-high", "text-on-surface-variant"),
    "primary": ("bg-primary-fixed", "text-primary"),
    "success": ("bg-green-100", "text-green-700"),
    "warning": ("bg-amber-100", "text-amber-700"),
    "error": ("bg-error-container", "text-error"),
}


def scorecard(
    label: str,
    value: Any,
    *,
    delta: Any = None,
    delta_color: str = "normal",
    icon: str | None = None,
    caption: str | None = None,
    kind: str = "default",
) -> str:
    """A standalone KPI **card**: a label, a big value, an optional trend ``delta``, an
    optional Material Symbols ``icon``, and an optional ``caption`` footer — where
    :func:`metric` is a bare KPI for composing, ``scorecard`` is the complete surface you
    drop into a :func:`grid` for a dashboard header row::

        ui.grid([
            ui.scorecard("Revenue", "$84.2k", delta="+8%", icon="payments", kind="primary"),
            ui.scorecard("Churn", "2.1%", delta="-0.4%", delta_color="inverse",
                         icon="trending_down", caption="vs last month"),
        ], cols=2)

    ``delta_color`` behaves as in :func:`metric` (``normal`` / ``inverse`` / ``off``).
    ``kind`` tints the icon — ``default`` / ``primary`` / ``success`` / ``warning`` /
    ``error``."""
    bg, fg = _SCORECARD_ACCENT.get(kind, _SCORECARD_ACCENT["default"])
    icon_html = ""
    if icon:
        icon_html = (
            f'<div class="flex items-center justify-center w-10 h-10 rounded-full {bg} {fg}">'
            f'<span class="material-symbols-outlined text-xl">{esc(icon)}</span></div>'
        )
    caption_html = ""
    if caption:
        caption_html = f'<p class="text-xs text-on-surface-variant mt-2">{esc(caption)}</p>'
    return (
        '<div class="golit-scorecard bg-surface-container-low rounded-xl p-5 shadow-sm">'
        '<div class="flex items-start justify-between gap-3">'
        '<span class="text-xs font-bold uppercase tracking-widest text-on-surface-variant">'
        f"{esc(label)}</span>{icon_html}</div>"
        '<div class="flex items-baseline gap-2 mt-2">'
        f'<span class="font-headline text-3xl font-bold tracking-tight">{esc(value)}</span>'
        f"{_delta_html(delta, delta_color)}</div>{caption_html}</div>"
    )


_ALERT = {
    "info": ("bg-blue-50 border-blue-200 text-blue-900", "info"),
    "success": ("bg-green-50 border-green-200 text-green-900", "check_circle"),
    "warning": ("bg-amber-50 border-amber-200 text-amber-900", "warning"),
    "error": ("bg-red-50 border-red-200 text-red-900", "error"),
}


def alert(*body: Any, kind: str = "info", title: str | None = None) -> str:
    """A callout. ``kind`` is info/success/warning/error."""
    cls, icon = _ALERT.get(kind, _ALERT["info"])
    title_html = f'<p class="font-semibold mb-0.5">{esc(title)}</p>' if title else ""
    return (
        f'<div class="golit-alert flex gap-3 border rounded-lg px-4 py-3 {cls}">'
        f'<span class="material-symbols-outlined text-xl">{icon}</span>'
        f'<div class="text-sm">{title_html}{_join(body)}</div></div>'
    )


_BADGE = {
    "default": "bg-surface-container-high text-on-surface-variant",
    "primary": "bg-primary-fixed text-primary",
    "secondary": "bg-secondary-container text-secondary",
    "success": "bg-green-100 text-green-800",
    "warning": "bg-amber-100 text-amber-900",
    "error": "bg-error-container text-error",
    "outline": "border border-outline-variant text-on-surface-variant",
}


def badge(text: Any, *, kind: str = "default") -> str:
    """A small status pill."""
    cls = _BADGE.get(kind, _BADGE["default"])
    return (
        '<span class="golit-badge inline-flex items-center px-2.5 py-0.5 rounded-full '
        f'text-xs font-semibold {cls}">{esc(text)}</span>'
    )


def progress(value: float, *, label: str | None = None, total: float = 1.0) -> str:
    """A progress bar. ``value`` is out of ``total`` (default a 0–1 fraction)."""
    frac = 0.0 if total == 0 else value / total
    pct = round(min(1.0, max(0.0, frac)) * 100, 1)
    head = ""
    if label:
        head = (
            '<div class="flex justify-between text-xs text-on-surface-variant mb-1">'
            f"<span>{esc(label)}</span><span>{pct:g}%</span></div>"
        )
    return (
        f'<div class="golit-progress">{head}'
        '<div class="w-full h-2 bg-surface-container-highest rounded-full overflow-hidden">'
        f'<div class="h-full bg-primary-container rounded-full transition-all" '
        f'style="width: {pct:g}%"></div></div></div>'
    )


def skeleton(*, lines: int = 3) -> str:
    """A loading placeholder of pulsing bars."""
    widths = [100, 92, 78, 96, 64]
    bars = "".join(
        '<div class="h-4 bg-surface-container-highest rounded animate-pulse" '
        f'style="width: {widths[i % len(widths)]}%"></div>'
        for i in range(max(1, lines))
    )
    return f'<div class="golit-skeleton flex flex-col gap-3">{bars}</div>'


def spinner(*, label: str | None = None) -> str:
    """An indeterminate spinner with an optional label."""
    lbl = f'<span class="text-sm text-on-surface-variant">{esc(label)}</span>' if label else ""
    return (
        '<div class="golit-spinner flex items-center gap-3">'
        '<div class="w-5 h-5 border-2 border-primary-container border-t-transparent '
        f'rounded-full animate-spin"></div>{lbl}</div>'
    )


# -- rich data ----------------------------------------------------------------

def table(df: Any, *, max_rows: int = 50, highlight: str | None = None) -> str:
    """A styled table from a Polars ``DataFrame``; ``highlight`` emphasizes a column.
    Non-DataFrame values fall back to the default renderer."""
    import polars as pl

    if not isinstance(df, pl.DataFrame):
        return render_value(df)
    head = df.head(max_rows)
    cols = "".join(
        f'<th class="px-4 py-3 text-left{" text-primary" if c == highlight else ""}">'
        f"{esc(c)}</th>"
        for c in head.columns
    )
    rows = "".join(
        '<tr class="hover:bg-surface-container transition-all">'
        + "".join(
            f'<td class="px-4 py-2.5 font-mono text-xs'
            f'{" text-primary font-semibold" if head.columns[i] == highlight else ""}">'
            f"{esc(v)}</td>"
            for i, v in enumerate(row)
        )
        + "</tr>"
        for row in head.iter_rows()
    )
    more = ""
    if df.height > max_rows:
        more = (
            '<p class="text-[10px] text-on-surface-variant text-right pt-2 font-mono uppercase '
            f'tracking-widest">showing {max_rows} of {df.height} rows</p>'
        )
    return (
        '<div class="golit-table-wrap overflow-x-auto">'
        '<table class="golit-table w-full text-left border-collapse">'
        '<thead><tr class="bg-surface-container-high/50 font-mono text-[10px] uppercase '
        f'tracking-widest text-outline">{cols}</tr></thead>'
        f'<tbody class="divide-y divide-outline-variant/10 text-sm">{rows}</tbody>'
        f"</table>{more}</div>"
    )


def code(src: str, *, lang: str | None = None) -> str:
    """A monospaced code block with an optional language tag."""
    tag = ""
    if lang:
        tag = (
            '<span class="absolute top-2 right-3 text-[10px] uppercase tracking-widest '
            f'text-outline font-mono">{esc(lang)}</span>'
        )
    return (
        f'<div class="golit-code relative">{tag}'
        '<pre class="bg-surface-container-highest rounded-lg p-4 overflow-x-auto text-xs '
        f'font-mono text-on-surface leading-relaxed"><code>{esc(src)}</code></pre></div>'
    )


def json_view(obj: Any, *, indent: int = 2) -> str:
    """Pretty-print a JSON-serializable object into a code block."""
    try:
        rendered = json.dumps(obj, indent=indent, default=str)
    except (TypeError, ValueError):
        rendered = str(obj)
    return code(rendered, lang="json")


def heading(text: str, *, level: int = 2) -> str:
    """A section heading (levels 1–6)."""
    level = min(6, max(1, level))
    size = {1: "text-3xl", 2: "text-2xl", 3: "text-xl", 4: "text-lg"}.get(level, "text-base")
    return (
        f'<h{level} class="golit-heading font-headline {size} font-bold tracking-tight">'
        f"{esc(text)}</h{level}>"
    )


def caption(text: str) -> str:
    """Small, muted helper text."""
    return f'<p class="golit-caption text-xs text-on-surface-variant">{esc(text)}</p>'


# -- realtime -----------------------------------------------------------------

def chat(
    channel: str,
    *,
    author: str = "You",
    title: str | None = None,
    placeholder: str = "Message…",
    height: int = 384,
) -> str:
    """A live chat panel backed by a WebSocket at ``/ws/<channel>``.

    Renders a message log that fills as messages arrive (over HTMX's ``ws``
    extension) and an input that sends over the socket. ``author`` is the sender's
    display name; ``height`` is the log height in pixels. By default every message
    relays to all clients on the channel; register an ``@app.on_message(channel)``
    handler to add bot/assistant/moderation behavior."""
    log_id = f"golit-chat-{esc(channel)}-log"
    head = (
        f'<div class="px-1 pb-3 font-headline text-lg font-bold tracking-tight">{esc(title)}</div>'
        if title
        else ""
    )
    return (
        '<div class="golit-chat flex flex-col bg-surface-container-low rounded-xl p-4" '
        f'hx-ext="ws" ws-connect="/ws/{esc(channel)}">{head}'
        f'<div id="{log_id}" class="golit-chat-log flex flex-col gap-2 overflow-y-auto pr-1" '
        f'style="height: {int(height)}px"></div>'
        '<form ws-send autocomplete="off" x-data x-on:submit="setTimeout(() => $el.reset(), 0)" '
        'class="golit-chat-form flex gap-2 mt-3">'
        f'<input type="hidden" name="author" value="{esc(author)}">'
        f'<input name="message" placeholder="{esc(placeholder)}" autocomplete="off" '
        'class="flex-1 bg-surface-container-highest border-none rounded-lg px-3 py-2 text-sm '
        'font-body text-on-surface focus:ring-2 focus:ring-primary">'
        '<button type="submit" class="bg-primary text-on-primary rounded-lg px-4 py-2 text-sm '
        'font-semibold hover:opacity-90 transition-all">Send</button>'
        "</form></div>"
    )


_CODE_CLS = 'bg-surface-container-highest rounded px-1.5 py-0.5 font-mono text-xs'


def _md_inline(text: str) -> str:
    out = esc(text)
    out = re.sub(r"`([^`]+)`", rf'<code class="{_CODE_CLS}">\1</code>', out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", out)
    out = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", out)
    out = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", out)
    link = r'<a class="text-primary underline" href="\2">\1</a>'
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, out)
    return out


def markdown(src: str) -> str:
    """Render a common Markdown subset (headings, emphasis, lists, blockquote,
    fenced code, links, rules) to styled HTML — no external dependency."""
    lines = src.split("\n")
    parts: list[str] = []
    para: list[str] = []
    items: list[str] = []
    list_tag: str | None = None

    def flush_para() -> None:
        if para:
            parts.append(f'<p class="mb-3 leading-relaxed">{_md_inline(" ".join(para))}</p>')
            para.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if items:
            cls = "list-decimal" if list_tag == "ol" else "list-disc"
            body = "".join(f"<li>{_md_inline(t)}</li>" for t in items)
            parts.append(f'<{list_tag} class="{cls} ml-6 mb-3 space-y-1">{body}</{list_tag}>')
            items.clear()
            list_tag = None

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("```"):
            flush_para()
            flush_list()
            lang = stripped[3:].strip() or None
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            parts.append(code("\n".join(buf), lang=lang))
            i += 1
            continue
        if not stripped:
            flush_para()
            flush_list()
        elif re.match(r"^#{1,6}\s", stripped):
            flush_para()
            flush_list()
            level = len(stripped) - len(stripped.lstrip("#"))
            size = {1: "text-2xl", 2: "text-xl", 3: "text-lg"}.get(level, "text-base")
            content = _md_inline(stripped[level:].strip())
            parts.append(
                f'<h{level} class="font-headline {size} font-bold tracking-tight mt-4 mb-2">'
                f"{content}</h{level}>"
            )
        elif stripped in ("---", "***", "___"):
            flush_para()
            flush_list()
            parts.append(divider())
        elif stripped.startswith("> "):
            flush_para()
            flush_list()
            parts.append(
                '<blockquote class="border-l-4 border-outline-variant pl-4 italic '
                f'text-on-surface-variant mb-3">{_md_inline(stripped[2:])}</blockquote>'
            )
        elif re.match(r"^[-*]\s+", stripped):
            flush_para()
            if list_tag not in (None, "ul"):
                flush_list()
            list_tag = "ul"
            items.append(re.sub(r"^[-*]\s+", "", stripped))
        elif re.match(r"^\d+\.\s+", stripped):
            flush_para()
            if list_tag not in (None, "ol"):
                flush_list()
            list_tag = "ol"
            items.append(re.sub(r"^\d+\.\s+", "", stripped))
        else:
            flush_list()
            para.append(stripped)
        i += 1

    flush_para()
    flush_list()
    return f'<div class="golit-markdown text-sm">{"".join(parts)}</div>'
