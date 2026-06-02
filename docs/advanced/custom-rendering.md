# Custom rendering

Golit knows how to render Polars frames, charts, components, and HTML strings out of the box (the full [resolution order](../tutorial/views.md#what-a-view-can-return)). When you have your *own* type — a domain object, a wrapper, a small visualization — you can teach Golit to render it directly, so views can return it like any built-in.

## The `Renderer` protocol

Give your object a `__golit_render__()` method that returns markup. It's checked **first** in the resolution order, so it wins over every default:

```python
from dataclasses import dataclass


@dataclass
class Gauge:
    value: int          # 0–100
    label: str = ""

    def __golit_render__(self) -> str:
        pct = max(0, min(100, self.value))
        return (
            f"<div class='golit-card'>"
            f"<p class='text-xs uppercase tracking-widest text-on-surface-variant'>{self.label}</p>"
            f"<div class='h-2 bg-surface-container-highest rounded-full mt-2'>"
            f"<div class='h-2 bg-primary-container rounded-full' style='width:{pct}%'></div>"
            f"</div></div>"
        )


@app.view
def health(score: int = slider(0, 100, default=70)) -> Gauge:
    return Gauge(score, label="System health")
```

Now `health` returns a `Gauge`, and Golit renders it through the protocol — no `str(...)` plumbing at the call site.

!!! tip "Escape what you interpolate"
    A `__golit_render__` result is trusted markup, exactly like a [returned string](../tutorial/views.md#returning-html). If you interpolate values that could contain user input, escape them — `from golit.widgets import esc` gives you the same HTML-escaping helper the built-in widgets use.

## Why a protocol, not a base class

`Renderer` is a `runtime_checkable` `Protocol`: any object with a `__golit_render__()` method qualifies — no import, no inheritance, no registration. Your types stay yours; they just happen to be renderable. It's duck typing with a name.

## The other extension points

You don't always need the protocol. Golit already honors several conventional hooks, so existing objects often render with no extra work:

| Your value has… | Golit renders it as… |
| --- | --- |
| `__golit_render__()` | its returned markup (the protocol) |
| `to_svg()` | wrapped SVG |
| `_repr_html_()` | that HTML (pandas, IPython-style reprs) |
| a Matplotlib figure (`savefig`) | SVG |

So a pandas DataFrame, a library object that already does `_repr_html_`, or anything that can emit SVG drops in without you writing a renderer.

## Composing with `golit.ui`

A `Renderer` nests inside [`golit.ui`](../tutorial/ui-components.md) components too, because those run every argument through the same resolver:

```python
import golit.ui as ui

@app.view
def dashboard(score: int = slider(0, 100)) -> str:
    return ui.card(Gauge(score, "Health"), title="Status")
```

`ui.card` renders the `Gauge` via its protocol method, then wraps it — same uniform pipeline a DataFrame or a chart figure would take.

## When to reach for raw HTML instead

If you only need a one-off bit of markup, just return a string from the view — you don't need a type. Reach for `__golit_render__` when the *same* object shows up in several views, when it carries state worth modeling, or when you want it to compose cleanly inside `golit.ui`.
