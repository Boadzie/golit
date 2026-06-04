# Golit

> A high-performance **Reactive Directed Acyclic Graph (DAG)** framework for building reactive data apps in Python. Golit maps your data dependencies, then on every interaction recomputes only the nodes that changed — not your whole script.

- **Rust reactive kernel** (PyO3) — dirty tracking, topological scheduling, propagation
- **Polars** data, held Python-side; only node ids/hashes cross the FFI boundary
- **SQL** — reactive nodes written as in-process **DuckDB** SQL over Polars frames (`golit.sql`)
- **Litestar** orchestration; **HTMX** server-rendered fragment transport (no client framework)
- **Charts** — Lets-Plot static SVG, plus interactive **Plotly / Altair / Bokeh / AnyChart**
- **Maps** — native **MapLibre GL** maps: **GeoDataFrame** vector + **rioxarray/xarray** raster + DuckDB spatial SQL (`golit.gis`)
- **Components** — reactive input widgets + a shadcn-styled **`golit.ui`** library
- **SSE** push channel with a pluggable pub/sub — in-memory single-node, **Redis** for a fleet
- **Tailwind + shadcn-styled** HTML, server-rendered (the `golit_pages` design system)

See [`project_scope.md`](project_scope.md) for the architecture and
[`golit_benchmark.md`](golit_benchmark.md) for the benchmark methodology.

## Install

```bash
pip install golit                 # core
pip install "golit[charts]"       # interactive Plotly / Altair / Bokeh
pip install "golit[sql]"          # DuckDB SQL nodes over Polars frames
pip install "golit[gis]"          # native MapLibre maps from GeoDataFrames
pip install "golit[gis-raster]"   # raster maps from rioxarray/xarray arrays
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
only on `data` (e.g. a dataset overview) is _not_ re-rendered on a slider move —
that selective recompute is the whole point. See
[`examples/sales_explorer/app.py`](examples/sales_explorer/app.py).

## How a change flows

1. **POST in** — a committed input (`hx-post`) runs the dirty subgraph; the response
   carries only the affected view fragments as out-of-band HTMX swaps.
2. **SSE out** — nodes dirtied server-side (streaming sources, background jobs,
   shared nodes) are pushed over `/events` as named `node:<id>` events.
3. **Memoization** — a node re-executes only when its inputs hash differently; an
   unchanged output cascades into memo hits downstream (nothing on the wire).

## Performance

The thesis is *update cost is proportional to the change, not the program* — and the
[benchmark harness](bench/) measures it (dev laptop, loopback; reproducible, not yet the
published cloud figure). The honest summary:

- **A single filter → chart updates in ~2 ms over HTTP — the same as Dash.** Idiomatic
  Dash is a hand-wired reactive DAG, so on one chain both do identical work and tie. Saying
  otherwise would be a strawman.
- **The gap opens on the shape real dashboards have: shared upstream work.** When one
  expensive step (a load, a join, a sort) feeds several views, moving a control that touches
  only one view makes Golit re-run *only* that view — the shared upstream is memoized and
  executes **zero** times — while Dash recomputes it every callback. Over real HTTP that's
  **~1.6× faster at 100K rows, ~5.5× at 1M, ~8.3× at 2M**, and the lead widens with the app.
- **`chart_spec` skips the figure object.** Returning a raw spec dict instead of a
  `go.Figure` cuts the per-update round-trip to ~1.5 ms and ~635 B (vs ~6.9 KB) — ~1.4×
  faster than figure-returning Dash with a ~10× smaller payload, same chart.

See [`bench/README.md`](bench/README.md) for the methodology and one-command repros.

## SQL nodes

A reactive node can be written as SQL instead of Polars. `golit.sql(query, **frames)`
runs **DuckDB** in-process over the named upstream frames and returns Polars, so the
node memoizes and renders like any other — inputs feed straight into the query.

```python
from golit import sql

@app.reactive
def by_region(data: pl.DataFrame, threshold: int = slider(0, 200, default=40)):
    return sql(
        "SELECT region, sum(revenue)::BIGINT AS revenue "
        f"FROM d WHERE revenue > {int(threshold)} GROUP BY region ORDER BY region",
        d=data,
    )
```

DuckDB exchanges data with Polars zero-copy. A raw `duckdb.sql(...)` relation returned
from a node is auto-detected and materialized too. Optional dependency: `pip install
"golit[sql]"`; it is imported only inside `sql()`, never at framework import time. See
[`examples/duckdb_sql/app.py`](examples/duckdb_sql/app.py).

## Charts

Lets-Plot renders to static SVG (no client runtime). For interactivity, return a
**Plotly, Altair, or Bokeh** figure — Golit auto-detects it and renders a
client-side chart that hydrates on the initial load _and_ across POST/SSE swaps.
**AnyChart** (no Python package) is available via `anychart()`.

```python
@app.view
def chart(by_region):
    import plotly.express as px
    return px.bar(by_region, x="region", y="revenue")   # Polars frame in directly
```

For a view that rebuilds its chart on every interaction, `chart_spec(lib, dict)` hands
Golit the raw wire-format spec directly, skipping the figure-object build and `to_json`
(see [Performance](#performance)). See
[`examples/charts_gallery/app.py`](examples/charts_gallery/app.py).

## Maps

A map is a reactive view like any other — a control rebuilds it. Return a GeoPandas
**`GeoDataFrame`** and Golit renders a native **MapLibre GL** map; `golit.gis.geo_map`
adds choropleths, tooltips, and basemaps, and `golit.gis.spatial_sql` runs DuckDB `ST_*`
queries that feed it. No client map framework — the server ships the GeoJSON and the
style rules; the GPU draws.

```python
import golit.gis as gis

@app.view
def map(regions):                      # regions is a filtered GeoDataFrame
    return gis.geo_map(regions, color="revenue", tooltip=["name", "revenue"])
```

Raster works too: `gis.raster(dataarray)` colormaps a georeferenced **rioxarray/xarray**
array (or GeoTIFF) to a MapLibre image layer (`pip install "golit[gis-raster]"`). Install
vector with `pip install "golit[gis]"` (DuckDB spatial rides on the `sql` extra). Moving a
control re-runs only the filter + map node — the fragment swaps in place on the initial load
and after a POST/SSE. See [`examples/geo_explorer/app.py`](examples/geo_explorer/app.py)
(vector) and [`examples/raster_explorer/app.py`](examples/raster_explorer/app.py) (raster).

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

## Page layout

By default views stack under one controls panel. `golit.layout` arranges the
reactive view fragments into a sidebar, rows, tabs, etc. — the layout is static
scaffold, so each view keeps its `id` and still swaps in place on POST/SSE.

```python
from golit import layout as L

app.layout = L.Sidebar(
    L.Controls(),                                  # all inputs, in the sidebar
    L.Stack(
        L.Row(L.View("kpi"), L.View("status")),
        L.Tabs({"Chart": L.View("chart"), "Data": L.View("table")}),
    ),
)
```

References are validated at build time: every `View`/`Control` must resolve to a
real view/input and be placed at most once.

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

| Tier | Role            | Tech                                                                |
| ---- | --------------- | ------------------------------------------------------------------- |
| 0    | Reactive kernel | Rust + PyO3 (`src/`, `golit._golit`)                                |
| 1    | Orchestrator    | Litestar + SSE/Redis fan-out (`golit.server`)                       |
| 2    | Transport       | HTMX fragments; static SVG, interactive charts, native maps (`golit.rendering`) |
| 3    | Local shield    | Alpine.js (widget immediacy, tab state)                             |

## Status

Built end-to-end and green (**17** cargo + **106** pytest, ruff + mypy clean): Rust
kernel, reactive engine, rendering (static **and** interactive charts, native MapLibre
maps), the `golit.ui` component library, page layout, DuckDB SQL nodes, GIS (vector **and** raster
maps + spatial SQL, `golit.gis`), Litestar server (POST + SSE), Redis pub/sub fan-out,
multi-worker deployment, the benchmark harness ([`bench/`](bench/), with measured
Golit-vs-Dash results), and the examples. **Deferred:** tiled rasters
(rio-tiler/titiler) + RGB composites, a standard-cloud-instance benchmark publication, and
the wider design suite in `golit_pages/`.

## Development

```bash
make dev      # set up venv + build extension
make test     # cargo test + pytest
make lint     # ruff + mypy
make build    # release wheel
```
