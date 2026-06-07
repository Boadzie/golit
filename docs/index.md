---
hide:
  - navigation
---

<div class="golit-hero" markdown>

# Golit

<p class="golit-tagline">Reactive data apps that actually ship.</p>

A high-performance **reactive DAG framework** for building data apps in Python. Golit maps your data dependencies once, then on every interaction recomputes **only the nodes that changed** — not your whole script.

</div>

<p align="center" markdown>
[Get started :material-arrow-right:](tutorial/first-app.md){ .md-button .md-button--primary }
[Why Golit?](#why-golit){ .md-button }
</p>

---

**Documentation:** you're reading it &nbsp;·&nbsp; **Source:** [github.com/boadzie/golit](https://github.com/boadzie/golit) &nbsp;·&nbsp; **License:** Apache-2.0

Golit closes the gap between rapid data prototyping (Streamlit, Dash) and production-grade, horizontally scalable web apps. It keeps the single-file, *write-Python-get-a-UI* ergonomics of prototyping tools, but replaces their wasteful execution model with a precise reactive engine backed by a **Rust compute kernel**.

## The key idea

Conventional data frameworks re-execute the **entire script** on every interaction. Move a slider and the framework re-loads the dataset, re-runs every transform, and re-renders every widget — even the 90% of the page that didn't change. Latency scales with *script size*, not with the size of the change.

Golit treats your app as a **dependency graph, not a script**:

1. An input changes and its node is marked **dirty**.
2. Dirtiness propagates downstream to *only* the transitively affected nodes.
3. Those nodes re-execute in topological order; everything else is a **memo hit**.
4. Only the UI fragments bound to recomputed nodes are re-rendered and swapped into the live DOM.

The result is updates whose cost is proportional to the **change**, not the program.

## Features

<div class="golit-grid" markdown>

<div markdown>
### :material-rocket-launch: Reactive by default
Plain Python functions become graph nodes. Dependencies are inferred from the function signature — no wiring, no callbacks.
</div>

<div markdown>
### :material-cog: Rust kernel
Dirty tracking, topological scheduling, and propagation run in a Rust + PyO3 kernel. The graph walk on every interaction never pays interpreter overhead.
</div>

<div markdown>
### :material-table: Polars data, zero-copy
DataFrames stay Python-side as Arrow buffers. Only node ids and `u64` content hashes cross the FFI boundary — never the data.
</div>

<div markdown>
### :material-swap-horizontal: HTMX fragment transport
The wire format is the final UI: pre-rendered HTML/SVG fragments swapped by HTMX. No client framework, no hydration, minimal payload.
</div>

<div markdown>
### :material-chart-bar: Charts, batteries included
Lets-Plot static SVG out of the box, plus auto-detected interactive **Plotly / Altair / Bokeh** and an **AnyChart** helper.
</div>

<div markdown>
### :material-map: Maps & GIS
Return a **GeoDataFrame** for a native **MapLibre GL** choropleth, or a **rioxarray/xarray** array for a raster layer — plus DuckDB **spatial SQL**. A map is a reactive view like any other.
</div>

<div markdown>
### :material-server-network: Scales horizontally
A single process needs nothing extra. Add **Redis** and a sticky load balancer to fan a fleet of workers out — server state stays worker-local by design.
</div>

</div>

## Requirements

Golit requires **Python 3.11+**. The core install pulls in [Litestar](https://litestar.dev/), [Polars](https://pola.rs/), [Lets-Plot](https://lets-plot.org/), and Uvicorn. Optional features (interactive charts, SQL nodes, Redis fan-out) are extras you opt into.

## Installation

```bash
pip install golit                 # core
pip install "golit[charts]"       # interactive Plotly / Altair / Bokeh
pip install "golit[sql]"          # DuckDB SQL nodes over Polars frames
pip install "golit[gis]"          # native MapLibre maps from GeoDataFrames
pip install "golit[gis-raster]"   # raster maps from rioxarray/xarray arrays
pip install "golit[redis]"        # Redis fan-out for multi-worker
```

## Example

Create a file `app.py`:

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
    return data.filter(pl.col("revenue") > threshold)  # re-runs only when data/threshold change


@app.view
def chart(filtered: pl.DataFrame):
    return ggplot(filtered, aes("region", "revenue")) + geom_bar(stat="identity") + ggsize(640, 360)


application = create_app(app)  # an ASGI app
```

### Run it

```bash
golit run app.py
```

Open <http://127.0.0.1:8000>. Moving the slider dirties `threshold → filtered → chart`. The `data` node is never touched; only the `chart` fragment is re-rendered and swapped.

!!! tip "That selective recompute *is* the whole point"
    A view that depends only on `data` (say, a dataset overview) is **not** re-rendered on a slider move. The framework does the minimum work the change requires — and nothing more.

## Why Golit?

|                  | Streamlit          | Dash        | **Golit**                  |
| ---------------- | ------------------ | ----------- | -------------------------- |
| Execution unit   | Full script        | Callback    | **Dirty subgraph**         |
| Update cost      | ∝ script size      | ∝ callback  | **∝ change**               |
| Wire format      | WebSocket diff     | JSON        | **HTML fragments**         |
| Data engine      | Pandas             | Pandas      | **Polars (Rust)**          |
| Charting         | Plotly/Altair (JS) | Plotly (JS) | **Lets-Plot → static SVG** |
| Maps / GIS       | pydeck / `st.map`  | dash-leaflet (JS) | **MapLibre from a GeoDataFrame** |
| Reactive core    | Python rerun       | Python      | **Rust (PyO3)**            |
| Horizontal scale | Hard               | Manual      | **Redis-backed, native**   |

[Read the full comparison :material-arrow-right:](about/comparison.md)

## Where to next

<div class="golit-grid" markdown>

<div markdown>
### :material-school: Tutorial
The hands-on **[User Guide](tutorial/index.md)** — build up from your first app to charts, components, layout, and SQL.
</div>

<div markdown>
### :material-lightbulb: Concepts
**[How it works](concepts/index.md)** — the reactive model, the four tiers, and how a change flows end-to-end.
</div>

<div markdown>
### :material-book-open-variant: Reference
The **[API reference](reference/index.md)**, generated from the source.
</div>

</div>
