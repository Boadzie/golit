# Inputs & widgets

A **widget** is a control the user interacts with. You use one as the **default value** of a node parameter, and Golit turns that parameter into an **input node** named after it.

```python
@app.reactive
def filtered(data, threshold: int = slider(0, 200, default=50)):
    #                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    #                  the default is a widget → `threshold` is an input node
    return data.filter(pl.col("revenue") > threshold)
```

When the user commits a new value, that input goes dirty and everything downstream re-runs. The function body receives the **typed Python value** — not the raw form string. Each widget knows how to *coerce* the posted string into the right type (an `int`, a `datetime.date`, a `list`, `BytesIO`, …).

!!! note "Labels are automatic"
    If you don't pass `label=`, Golit derives one from the parameter name: `min_revenue` → "Min Revenue". Pass `label=` to override.

## The catalog

All widgets are importable from the top-level `golit` package. Each has an ergonomic lowercase factory (`slider`, `select`, …) and an underlying class (`Slider`, `Select`, …) — use the factory.

### slider

A numeric range slider. Commits on **release** (`change`); while dragging, an Alpine.js "local shield" shows the live value without touching the server.

```python
from golit import slider

threshold: int = slider(0, 200, default=50, step=5, label="Min revenue")
```

`slider(low, high, *, default=low, step=1, label=None)`. If the bounds, step, and default are all whole numbers, values coerce to `int`; otherwise `float`.

### number

A numeric text input with optional bounds.

```python
from golit import number

qty: int = number(0, 100, default=10, step=1, label="Quantity")
```

`number(low=None, high=None, *, default=0, step=1, label=None)`. Coerces to `int` when step and default are whole, else `float`.

### select

A dropdown of options; the value is the chosen **option object** (not its string form).

```python
from golit import select

region: str = select(["All", "North", "South"], default="All", label="Region")
```

`select(options, *, default=options[0], label=None)`.

### radio

A single choice shown as radio buttons. Same value semantics as `select`.

```python
from golit import radio

plan: str = radio(["Free", "Pro", "Team"], default="Free")
```

### multiselect

Zero or more choices, as a checkbox group. The value is a **`list`** of the chosen option objects, in option order.

```python
from golit import multiselect

regions: list = multiselect(["North", "South", "East", "West"], default=["North"], label="Regions")
```

`multiselect(options, *, default=(), label=None)`.

### text

A single-line text input. Commits on blur (`change`) **and** after a short typing pause (`keyup` debounced ~400ms).

```python
from golit import text

query: str = text(default="", placeholder="Search…", label="Query")
```

### textarea

Multi-line text. Same commit triggers as `text`.

```python
from golit import textarea

notes: str = textarea(default="", rows=6, placeholder="Notes…")
```

### checkbox

A boolean checkbox. Posts an explicit `true`/`false` so an *unchecked* box still commits a value.

```python
from golit import checkbox

include_tax: bool = checkbox(default=True, label="Include tax")
```

### switch

A boolean toggle (a styled checkbox). Same semantics as `checkbox`, different look.

```python
from golit import switch

compact: bool = switch("Compact view", default=False)
```

### date

A native date picker. Coerces the ISO string to a `datetime.date` (or `None` when empty).

```python
import datetime
from golit import date

day: datetime.date = date(default=datetime.date(2026, 1, 1), label="As of")
```

### upload

A file upload. Coerces the posted bytes into a `BytesIO`, which Polars readers accept directly — so you can pass it straight to `pl.read_csv`.

```python
import polars as pl
from golit import upload

@app.source
def data(file=upload("Upload CSV", accept=".csv")) -> pl.DataFrame:
    return SAMPLE if file is None else pl.read_csv(file)
```

`upload(label=None, *, accept=None)`. The value is `None` until a file is chosen, so guard for it.

### button

An action trigger — the reactive equivalent of "on click". Each click posts a fresh nonce (a monotonic counter), so the input's value *changes* and its dirty subgraph re-runs. The value itself is usually ignored.

```python
from golit import button

@app.view
def report(go: int = button("Generate", kind="primary")) -> str:
    # Re-runs on every click because `go` changes each time.
    return build_report()
```

`button(label=None, *, kind="primary")` — `kind` is `"primary"`, `"secondary"`, or `"ghost"`.

## How a value travels

When you move a control:

1. HTMX posts the new value to `POST /node/{input_id}`.
2. Golit calls the widget's `coerce()` to type it, stores it for the session, and runs the dirty subgraph.
3. The response carries **only the changed view fragments**, swapped in place.

High-frequency events (slider drag, keystrokes) are absorbed client-side by Alpine and HTMX's debouncing, so the server only sees *committed* changes — see [Architecture: the Local Shield](../concepts/architecture.md#tier-3-local-shield-alpinejs).

## Multiple inputs, one node

A node can take any number of inputs and dependencies together — they're just parameters:

```python
@app.reactive
def filtered(
    data: pl.DataFrame,                                          # dependency
    threshold: int = slider(0, 200, default=50),                # input
    region: str = select(REGIONS, default="All"),              # input
) -> pl.DataFrame:
    out = data.filter(pl.col("revenue") > threshold)
    return out if region == "All" else out.filter(pl.col("region") == region)
```

Changing *either* input dirties `filtered` and everything downstream of it — and nothing else.

## Next

Now the other half of a node function: what a view can **return**. See **[Views & rendering](views.md)**.
