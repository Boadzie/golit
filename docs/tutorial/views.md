# Views & rendering

A **view** (`@app.view`) is a renderable leaf. Whatever it returns, Golit turns into an HTML fragment and swaps into a `<section>` keyed by the view's id. Because the transport is just HTML fragments, a view can return many different things — and Golit picks how to render based on the *type* of the value.

## What a view can return

Golit resolves a return value in this order — **first match wins**:

1. An object with a **`__golit_render__()`** method (the [`Renderer`](../advanced/custom-rendering.md) protocol) → its returned markup.
2. A **`str`** → used verbatim as **trusted, developer-authored markup**.
3. **`bytes`** → decoded as UTF-8.
4. A **Lets-Plot** spec → rendered to static **SVG**.
5. A **Plotly / Altair / Bokeh** figure → an interactive client-side chart mount.
6. Anything with **`to_svg()`** → wrapped as SVG.
7. A **Polars `DataFrame`** → a styled HTML table.
8. A **DuckDB relation** → materialized to Polars, then a table.
9. A **[Great Tables](https://posit-dev.github.io/great-tables/) `GT`** object → its self-contained HTML.
10. Anything with **`_repr_html_()`** (e.g. pandas) → that HTML.
11. A **Matplotlib** figure → SVG via `savefig`.
12. Anything else → its `repr()`, escaped, in a `<pre>`.

`None` renders as empty.

!!! danger "Strings are trusted HTML"
    A `str` you return is inserted **without escaping** — it's meant for markup you wrote. Never interpolate untrusted user input into a returned string without escaping it yourself. For escaping a value, `golit.widgets.esc` (or Python's `html.escape`) is right there. For *data*, return a DataFrame or use [`golit.ui`](ui-components.md) components, which escape for you.

## Returning HTML

The simplest view returns a string:

```python
@app.view
def kpi(filtered: pl.DataFrame) -> str:
    total = int(filtered["revenue"].sum()) if filtered.height else 0
    return f"<h3 class='text-3xl font-bold'>${total:,}</h3>"
```

Golit's page shell loads **Tailwind** (with the Material-3 token palette) and the `golit.ui` styles, so utility classes like `text-3xl`, `bg-surface-container-low`, and `text-primary` are available in your markup. You don't have to use them — any HTML works.

## Returning a DataFrame

Return a Polars frame and get a styled, paginated table for free:

```python
@app.view
def table(filtered: pl.DataFrame) -> pl.DataFrame:
    return filtered
```

The default table shows up to 50 rows with a "showing 50 of N" footer. For more control (row cap, column highlight), use [`golit.ui.table`](ui-components.md#rich-data).

## Returning a Great Tables table

For a *polished* display table — formatted currency, spanners, source notes, embedded bars — build a [Great Tables](https://posit-dev.github.io/great-tables/) `GT` object from your Polars (or pandas) frame and return it. Golit detects it and embeds its self-contained HTML — the styles are scoped to the table and there's no JavaScript, so it just works inside the page, and it re-renders reactively like any view:

```python
from great_tables import GT

@app.view
def report(filtered: pl.DataFrame):
    return (
        GT(filtered, rowname_col="Region")
        .tab_header(title="Regional Sales")
        .fmt_currency(columns="Revenue", decimals=0)
        .fmt_percent(columns="Growth", decimals=1)
    )
```

Needs the extra: `pip install "golit[tables]"`. See [`examples/great_tables`](https://github.com/boadzie/golit/tree/main/examples/great_tables).

## Returning a chart

Return a Lets-Plot spec, or a Plotly/Altair/Bokeh figure — Golit detects each and renders appropriately. That's the whole next chapter: **[Charts](charts.md)**.

## Returning a component

The [`golit.ui`](ui-components.md) builders return strings of styled HTML, so you can return one directly, or compose several:

```python
import golit.ui as ui

@app.view
def panel(by_region, total: int) -> str:
    return ui.card(
        ui.metric("Revenue", f"${total:,}", delta="+8%"),
        ui.table(by_region, highlight="revenue"),
        title="Overview",
    )
```

## A view re-renders only when its inputs change

A view is a node like any other. It re-renders when something it depends on produces a new value — and is skipped otherwise. The classic illustration, from the `sales_explorer` example:

```python
@app.view
def overview(data: pl.DataFrame) -> str:
    # Depends only on `data` — unaffected by the slider/region inputs.
    return f"<p>{data.height} rows · ${int(data['revenue'].sum()):,} total</p>"
```

Moving a slider that feeds a *different* view leaves `overview` exactly as it was — no recompute, no swap, nothing on the wire.

## Next

**[Charts](charts.md)** — static SVG and interactive figures, from the same Polars frame.
