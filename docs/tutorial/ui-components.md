# UI components

`golit.ui` is a library of **presentational** components — shadcn-styled, server-rendered HTML. Unlike [widgets](inputs.md) (which are reactive *inputs*), these are pure builders a view returns. Each takes renderables and produces a styled HTML string.

```python
import golit.ui as ui
```

## They compose through the renderer

Every component argument is run through Golit's [`render_value`](views.md#what-a-view-can-return), so you can nest **anything** uniformly — a DataFrame, a chart figure, another component, or trusted HTML:

```python
@app.view
def panel(by_region: pl.DataFrame, total: int) -> str:
    return ui.card(
        ui.columns([
            ui.metric("Revenue", f"${total:,}", delta="+8%"),
            ui.table(by_region, highlight="revenue"),
        ]),
        title="Overview",
    )
```

That uniformity is the point: a `card` doesn't care whether you hand it a string, a frame, or another `card`.

## Layout & containers

| Component | Purpose |
| --- | --- |
| `card(*body, title=None, subtitle=None, footer=None)` | A surface card with optional header/footer. |
| `columns(items, *, gap=6, widths=None)` | A responsive row; `widths` (summing to 12) gives a custom split. |
| `grid(items, *, cols=3, gap=6)` | A fixed-column responsive grid (1 → 2 → `cols`). |
| `tabs(panels, *, default=None)` | A client-side tab group (Alpine); `panels` maps label → renderable. |
| `expander(title, *body, open=False)` | A collapsible section (native `<details>`). |
| `accordion(sections)` | A stack of independently collapsible sections. |
| `divider(*, label=None)` | A horizontal rule, optionally labeled. |

## Display & status

| Component | Purpose |
| --- | --- |
| `metric(label, value, *, delta=None, delta_color="normal", help=None)` | A bare KPI: big value, label, optional up/down delta. |
| `scorecard(label, value, *, delta=None, delta_color="normal", icon=None, caption=None, kind="default")` | A standalone KPI **card** — icon, value, trend, caption. Drop several in a `grid` for a header row. |
| `alert(*body, kind="info", title=None)` | A callout — `info` / `success` / `warning` / `error`. |
| `badge(text, *, kind="default")` | A small status pill. |
| `progress(value, *, label=None, total=1.0)` | A progress bar; `value` is out of `total`. |
| `skeleton(*, lines=3)` | A loading placeholder of pulsing bars. |
| `spinner(*, label=None)` | An indeterminate spinner. |

`metric`'s `delta_color`: `"normal"` (up = good/green), `"inverse"` (down = good), or `"off"` (neutral). A leading `-` in the delta marks it down.

## Rich data

| Component | Purpose |
| --- | --- |
| `table(df, *, max_rows=50, highlight=None)` | A styled table from a Polars frame; `highlight` emphasizes a column. |
| `markdown(src)` | A common-Markdown-subset renderer (headings, emphasis, lists, blockquote, fenced code, links, rules) — no external dependency. |
| `code(src, *, lang=None)` | A monospaced code block with an optional language tag. |
| `json_view(obj, *, indent=2)` | Pretty-printed JSON in a code block. |
| `heading(text, *, level=2)` | A section heading (levels 1–6). |
| `caption(text)` | Small, muted helper text. |

## Realtime

| Component | Purpose |
| --- | --- |
| `chat(channel, *, author="You", title=None, …)` | A live, WebSocket-backed chat panel. |
| `webcam(name, *, title=None, height=384, width=None)` | A live video panel showing a server-side MJPEG stream. |

These two are different from the others: rather than rendering once, they hold a live connection and update on their own. `chat` opens a bidirectional WebSocket and appends messages as they arrive — see [WebSocket chat](../advanced/websockets.md). `webcam` shows a frame producer registered with `@app.stream(name)` as native MJPEG in a plain `<img>` — see [Video streams](../advanced/video-streams.md).

## A worked example

```python
import golit.ui as ui


@app.view
def status(filtered: pl.DataFrame) -> str:
    if not filtered.height:
        return ui.alert("No rows match the current filter.", kind="warning", title="Empty")
    return ui.alert(
        ui.badge(f"{filtered.height} rows", kind="primary") + " match the filter.",
        kind="success",
        title="Live",
    )


@app.view
def detail(filtered: pl.DataFrame, compact: bool = switch("Compact", default=False)) -> str:
    shown = filtered.select("region", "revenue") if compact else filtered
    summary = ui.markdown(f"### Summary\n\n- **{filtered.height}** rows after filtering\n")
    return ui.card(
        ui.tabs({"Table": ui.table(shown, highlight="revenue"), "Summary": summary}),
        title="Detail",
    )
```

The [`components_gallery`](https://github.com/boadzie/golit/tree/main/examples/components_gallery) example wires these into a full reactive dashboard.

!!! note "Escaping"
    `golit.ui` components escape the values you pass through them, so it's safe to feed user data into `metric`, `badge`, `table`, and friends. The exception is a raw `str` you build yourself and return from a view — that's [trusted markup](views.md#returning-html).

## Next

Arrange your views on the page: **[Page layout](layout.md)**.
