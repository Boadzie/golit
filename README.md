# Golit

> **Streamlit, until it goes to production.**

A high-performance **Reactive Directed Acyclic Graph (DAG)** framework for Python.
Golit maps your data dependencies, then on every interaction recomputes only the
nodes that changed — not your whole script.

- **Rust reactive kernel** (PyO3) — dirty tracking, topological scheduling, propagation
- **Polars** data, held Python-side; only node ids/hashes cross the FFI boundary
- **Litestar** orchestration; **HTMX** server-rendered fragment transport (no client framework)
- **Charts** — Lets-Plot static SVG, plus interactive **Plotly / Altair / Bokeh / AnyChart**
- **Components** — reactive input widgets + a shadcn-styled **`golit.ui`** library
- **SSE** push channel with a pluggable pub/sub — in-memory single-node, **Redis** for a fleet
- **Tailwind + shadcn-styled** HTML, server-rendered (the `golit_pages` design system)

See [`project_scope.md`](project_scope.md) for the architecture and
[`golit_benchmark.md`](golit_benchmark.md) for the benchmark methodology.

## Install

```bash
pip install golit                 # core
pip install "golit[charts]"       # interactive Plotly / Altair / Bokeh
pip install "golit[redis]"        # Redis fan-out for multi-worker
```

## Quickstart

```bash
make dev     # uv venv (3.11) + deps + build the Rust kernel (maturin)
make test    # cargo test + pytest
make run     # golit run examples/sales_explorer/app.py
```

Then open <http://127.0.0.1:8000>.

## The programming model

Nodes are plain Python functions. Dependencies are inferred from parameters: a
parameter named after another node is an **edge**; a parameter defaulting to a
**widget** is an **input**.

```python
import polars as pl
from golit import App, create_app, slider, upload
from golit.charts import aes, geom_bar, ggplot, ggsize

app = App(title="Sales Explorer")

@app.source
def data(file=upload("Upload CSV")) -> pl.DataFrame:
    return pl.read_csv(file)

@app.reactive
def filtered(data: pl.DataFrame, threshold: int = slider(0, 100, default=20)) -> pl.DataFrame:
    return data.filter(pl.col("revenue") > threshold)   # re-runs only when data/threshold change

@app.view
def chart(filtered: pl.DataFrame):
    return ggplot(filtered, aes("region", "revenue")) + geom_bar(stat="identity") + ggsize(640, 360)

application = create_app(app)   # an ASGI app; `golit run app.py` serves it
```

Moving the slider dirties `threshold → filtered → chart`. The `data` node is never
touched; only the `chart` fragment is re-rendered and swapped. A view that depends
only on `data` (e.g. a dataset overview) is *not* re-rendered on a slider move —
that selective recompute is the whole point. See
[`examples/sales_explorer/app.py`](examples/sales_explorer/app.py).

## How a change flows

1. **POST in** — a committed input (`hx-post`) runs the dirty subgraph; the response
   carries only the affected view fragments as out-of-band HTMX swaps.
2. **SSE out** — nodes dirtied server-side (streaming sources, background jobs,
   shared nodes) are pushed over `/events` as named `node:<id>` events.
3. **Memoization** — a node re-executes only when its inputs hash differently; an
   unchanged output cascades into memo hits downstream (nothing on the wire).

## Charts

Lets-Plot renders to static SVG (no client runtime). For interactivity, return a
**Plotly, Altair, or Bokeh** figure — Golit auto-detects it and renders a
client-side chart that hydrates on the initial load *and* across POST/SSE swaps.
**AnyChart** (no Python package) is available via `anychart()`.

```python
@app.view
def chart(by_region):
    import plotly.express as px
    return px.bar(by_region, x="region", y="revenue")   # Polars frame in directly
```

See [`examples/charts_gallery/app.py`](examples/charts_gallery/app.py).

## Components

**Inputs** (reactive) — `slider`, `number`, `select`, `text`, `checkbox`, `upload`,
`radio`, `multiselect`, `switch`, `date`, `textarea`, `button`.

**Display** (`golit.ui`) — `card`, `columns`, `grid`, `tabs`, `expander`,
`accordion`, `divider`, `metric`, `alert`, `badge`, `progress`, `skeleton`,
`spinner`, `table`, `markdown`, `code`, `json_view`, `heading`, `caption`.

```python
import golit.ui as ui

@app.view
def panel(by_region, total):
    return ui.card(
        ui.columns([ui.metric("Revenue", f"${total:,}", delta="+8%"), chart_fig]),
        title="Overview",
    )
```

Components compose through the renderer, so any argument can be a DataFrame, a
chart figure, another component, or trusted HTML. See
[`examples/components_gallery/app.py`](examples/components_gallery/app.py).

## Deploying & scaling

A single process needs nothing extra. To scale horizontally, set `GOLIT_REDIS_URL`
and run **N single-worker instances behind a sticky (session-cookie) load
balancer** — session state is worker-local by design, and Redis fans server-side
invalidations across the fleet. A runnable podman/nginx stack lives in
[`deploy/`](deploy/).

```bash
pip install "golit[redis]"
export GOLIT_REDIS_URL=redis://localhost:6379
golit run examples/sales_explorer/app.py
```

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for the full topology and why `uvicorn
--workers` can't provide session affinity.

## Architecture (tiers)

| Tier | Role            | Tech                                                            |
| ---- | --------------- | -------------------------------------------------------------- |
| 0    | Reactive kernel | Rust + PyO3 (`src/`, `golit._golit`)                           |
| 1    | Orchestrator    | Litestar + SSE/Redis fan-out (`golit.server`)                 |
| 2    | Transport       | HTMX fragments; static SVG + interactive charts (`golit.rendering`) |
| 3    | Local shield    | Alpine.js (widget immediacy, tab state)                        |

## Status

Built end-to-end and green (**13** cargo + **59** pytest, ruff + mypy clean): Rust
kernel, reactive engine, rendering (static **and** interactive charts), the
`golit.ui` component library, Litestar server (POST + SSE), Redis pub/sub fan-out,
multi-worker deployment, and the examples. **Deferred:** the benchmark harness and
rival apps, and the wider design suite in `golit_pages/`.

## Development

```bash
make dev      # set up venv + build extension
make test     # cargo test + pytest
make lint     # ruff + mypy
make build    # release wheel
```
