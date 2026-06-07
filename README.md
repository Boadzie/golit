<div align="center">

# Golit

**Reactive data apps that actually ship.**

A high-performance reactive **Directed Acyclic Graph (DAG)** framework for Python. Golit maps your
data dependencies once, then on every interaction recomputes **only the nodes that changed** — not
your whole script.

[![version](https://img.shields.io/badge/version-1.0.0-blue?style=flat-square)](CHANGELOG.md)
[![python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-Apache--2.0-green?style=flat-square)](#license)
[![tests](https://img.shields.io/badge/tests-226%20passing-brightgreen?style=flat-square)](#status)
[![built with](https://img.shields.io/badge/built%20with-Rust%20%2B%20PyO3-000000?style=flat-square&logo=rust)](src/)
[![changelog](https://img.shields.io/badge/changelog-1.0.0-orange?style=flat-square)](CHANGELOG.md)

[Documentation](docs/) · [Changelog](CHANGELOG.md) · [Examples](examples/) · [Benchmarks](bench/) · [Architecture](project_scope.md) · [Deployment](DEPLOYMENT.md)

</div>

---

Golit pairs the authoring speed of a notebook-style data app with the runtime discipline of a
compiled reactive graph. Your dashboard is a set of plain Python functions; Golit infers the
dependency graph between them, and a Rust kernel ensures a user interaction re-runs the minimal
subgraph it touched and ships only the affected HTML fragments over the wire. The guiding thesis:
**update cost is proportional to the change, not the size of the program.**

## Features

- **Rust reactive kernel** (PyO3) — dirty tracking, topological scheduling, memoized propagation.
- **Polars** data held Python-side; only node ids/hashes cross the FFI boundary.
- **SQL nodes** — reactive nodes written as in-process **DuckDB** SQL over Polars frames (`golit.sql`).
- **Litestar** orchestration with **HTMX** server-rendered fragment transport — no client framework.
- **Charts** — Lets-Plot static SVG, plus interactive **Plotly / Altair / Bokeh / AnyChart**.
- **Tables** — styled tables from Polars, or return a **[Great Tables](https://posit-dev.github.io/great-tables/) `GT`** object for a polished, auto-rendered display table.
- **Maps** — native **MapLibre GL**: **GeoDataFrame** vector, **rioxarray/xarray** raster, and DuckDB spatial SQL (`golit.gis`).
- **Components** — reactive input widgets plus a shadcn-styled **`golit.ui`** library, server-rendered with Tailwind.
- **Realtime** — **SSE** push with pluggable pub/sub (in-memory or **Redis**), WebSocket **chat**, **video** (server-side MJPEG + browser-camera CV), and **audio** (mic recorder).
- **Live sources** — `@app.poll` streams external data that changes on its own (a Google Sheet, an API); only real changes re-render and hit the wire.
- **Scales horizontally** — N single-worker instances behind a sticky load balancer with Redis fan-out.

## Installation

Golit ships prebuilt wheels for Python 3.11+ (the `abi3` stable ABI):

```bash
pip install golit                 # core
pip install "golit[charts]"       # interactive Plotly / Altair / Bokeh
pip install "golit[sql]"          # DuckDB SQL nodes over Polars frames
pip install "golit[gis]"          # native MapLibre maps from GeoDataFrames
pip install "golit[gis-raster]"   # raster maps from rioxarray/xarray arrays
pip install "golit[tables]"       # Great Tables display tables (auto-rendered from a view)
pip install "golit[vision]"       # webcam / MJPEG video streams (Pillow)
pip install "golit[vision-cv]"    # + OpenCV for real CV models (face detection)
pip install "golit[redis]"        # Redis fan-out for multi-worker
```

## Quickstart

```bash
make dev     # uv venv (3.11) + deps + build the Rust kernel (maturin)
make test    # cargo test + pytest
make run     # golit run examples/sales_explorer/app.py
```

Then open <http://127.0.0.1:8000>.

## Programming model

Nodes are plain Python functions. Dependencies are inferred from parameters: a parameter named
after another node is an **edge**; a parameter defaulting to a **widget** is an **input**.

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

Moving the slider dirties `threshold → filtered → chart`. The `data` node is never touched; only
the `chart` fragment is re-rendered and swapped. A view that depends only on `data` (e.g. a dataset
overview) is _not_ re-rendered on a slider move — that selective recompute is the whole point. See
[`examples/sales_explorer/app.py`](examples/sales_explorer/app.py).

## How a change flows

1. **POST in** — a committed input (`hx-post`) runs the dirty subgraph; the response carries only
   the affected view fragments as out-of-band HTMX swaps.
2. **SSE out** — nodes dirtied server-side (streaming sources, background jobs, shared nodes) are
   pushed over `/events` as named `node:<id>` events.
3. **Memoization** — a node re-executes only when its inputs hash differently; an unchanged output
   cascades into memo hits downstream (nothing on the wire).

## Performance

The thesis is *update cost is proportional to the change, not the program* — and the
[benchmark harness](bench/) measures it (dev laptop, loopback; reproducible, not yet the published
cloud figure). The honest summary:

- **A single filter → chart updates in ~2 ms over HTTP — the same as Dash.** Idiomatic Dash is a
  hand-wired reactive DAG, so on one chain both do identical work and tie. Saying otherwise would be
  a strawman.
- **The gap opens on the shape real dashboards have: shared upstream work.** When one expensive step
  (a load, a join, a sort) feeds several views, moving a control that touches only one view makes
  Golit re-run *only* that view — the shared upstream is memoized and executes **zero** times —
  while Dash recomputes it every callback. Over real HTTP that's **~1.6× faster at 100K rows, ~5.5×
  at 1M, ~8.3× at 2M**, and the lead widens with the app.
- **`chart_spec` skips the figure object.** Returning a raw spec dict instead of a `go.Figure` cuts
  the per-update round-trip to ~1.5 ms and ~635 B (vs ~6.9 KB) — ~1.4× faster than figure-returning
  Dash with a ~10× smaller payload, same chart.

See [`bench/README.md`](bench/README.md) for the methodology and one-command repros.

## SQL nodes

A reactive node can be written as SQL instead of Polars. `golit.sql(query, **frames)` runs **DuckDB**
in-process over the named upstream frames and returns Polars, so the node memoizes and renders like
any other — inputs feed straight into the query.

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

DuckDB exchanges data with Polars zero-copy. A raw `duckdb.sql(...)` relation returned from a node is
auto-detected and materialized too. Optional dependency: `pip install "golit[sql]"`; it is imported
only inside `sql()`, never at framework import time. See
[`examples/duckdb_sql/app.py`](examples/duckdb_sql/app.py).

## Charts

Lets-Plot renders to static SVG (no client runtime). For interactivity, return a **Plotly, Altair,
or Bokeh** figure — Golit auto-detects it and renders a client-side chart that hydrates on the
initial load _and_ across POST/SSE swaps. **AnyChart** (no Python package) is available via
`anychart()`.

```python
@app.view
def chart(by_region):
    import plotly.express as px
    return px.bar(by_region, x="region", y="revenue")   # Polars frame in directly
```

For a view that rebuilds its chart on every interaction, `chart_spec(lib, dict)` hands Golit the raw
wire-format spec directly, skipping the figure-object build and `to_json` (see
[Performance](#performance)). See [`examples/charts_gallery/app.py`](examples/charts_gallery/app.py).

## Maps

A map is a reactive view like any other — a control rebuilds it. Return a GeoPandas
**`GeoDataFrame`** and Golit renders a native **MapLibre GL** map; `golit.gis.geo_map` adds
choropleths, tooltips, and basemaps, and `golit.gis.spatial_sql` runs DuckDB `ST_*` queries that feed
it. No client map framework — the server ships the GeoJSON and the style rules; the GPU draws. For
**large** vector data, `golit.gis.vector_tiles` keeps the GeoDataFrame server-side and streams **MVT
vector tiles** (`pip install "golit[gis-vector-tiles]"`) so 100k+ features render without inlining
the whole GeoJSON.

```python
import golit.gis as gis

@app.view
def map(regions):                      # regions is a filtered GeoDataFrame
    return gis.geo_map(regions, color="revenue", tooltip=["name", "revenue"])
```

Raster works too: `gis.raster(dataarray)` colormaps a georeferenced **rioxarray/xarray** array (or
GeoTIFF) to a MapLibre image layer, `gis.rgb(stack, bands=…)` renders a multiband raster as a
true/false-color **satellite composite** (`pip install "golit[gis-raster]"`), and
`gis.tiles("scene.tif")` streams a **very large COG** as on-demand `z/x/y` tiles via rio-tiler
(`pip install "golit[gis-tiles]"`) — only the visible window crosses the wire. And
`gis.terrain(dem, "hillshade")` runs **WhiteboxTools** terrain analysis (slope, flow accumulation, …)
into a renderable raster (`pip install "golit[gis-terrain]"`), and `gis.ee_layer(image, vis=…)`
overlays **Google Earth Engine** imagery as live tiles (`pip install "golit[gis-ee]"`). Install
vector with `pip install "golit[gis]"` (DuckDB spatial rides on the `sql` extra). Moving a control
re-runs only the filter + map node — the fragment swaps in place on the initial load and after a
POST/SSE. See
[`examples/geo_explorer/app.py`](examples/geo_explorer/app.py) (vector),
[`examples/vector_tiles/app.py`](examples/vector_tiles/app.py) (60k-feature vector tiles),
[`examples/raster_explorer/app.py`](examples/raster_explorer/app.py) (raster),
[`examples/rgb_composite/app.py`](examples/rgb_composite/app.py) (RGB composite),
[`examples/tiled_raster/app.py`](examples/tiled_raster/app.py) (tiled COG),
[`examples/terrain_analysis/app.py`](examples/terrain_analysis/app.py) (terrain), and
[`examples/earth_engine/app.py`](examples/earth_engine/app.py) (Earth Engine).

## Realtime: video and audio

Some views don't re-render on a change — they hold a **live connection**. `golit.ui.chat(channel)`
opens a WebSocket-backed chat panel (`@app.on_message` adds bot/moderation logic). For computer
vision, `@app.stream(name)` + `ui.webcam(name)` push a **server-side MJPEG** feed the browser plays
in a plain `<img>` — a host camera, a detector drawing boxes, a synthetic animation — and
`shared=True` fans one producer out to many viewers. The mirror, `@app.on_frame(name)` +
`ui.camera(name)`, streams the **visitor's own webcam** up over a WebSocket, runs your handler on each
frame server-side, and paints the annotated result back.

```python
import numpy as np
import golit.ui as ui

@app.on_frame("faces")
def detect(frame: np.ndarray) -> np.ndarray:   # (H, W, 3) uint8 RGB in and out
    ...                                          # run your model, draw boxes
    return frame

@app.view
def live() -> str:
    return ui.camera("faces", title="Your camera")
```

Frames are JPEG `bytes` or `(H, W, 3)` RGB arrays (encoded with Pillow). Sync handlers run in a
worker thread; one frame is in flight at a time, so a slow model lowers the rate instead of backing
up, and a producer/handler that errors is logged without dropping the stream. `pip install
"golit[vision]"` (or `[vision-cv]` for OpenCV). See
[`examples/webcam_stream`](examples/webcam_stream/app.py) (server feed),
[`examples/browser_camera`](examples/browser_camera/app.py) (browser camera), and
[`examples/face_detect`](examples/face_detect/app.py) (real OpenCV face detection).

For **audio**, `ui.recorder(name)` captures the visitor's mic and uploads each clip as 16-bit WAV
(with inline playback + a download link for the clip); the `@app.on_audio(name)` handler decodes it
(Python's stdlib `wave` — no ffmpeg) and returns a result to show, or audio to play back. See
[`examples/audio_recorder`](examples/audio_recorder/app.py) and
[Audio recording](docs/advanced/audio.md).

## Components

**Inputs** (reactive) — `slider`, `number`, `select`, `text`, `checkbox`, `upload`, `radio`,
`multiselect`, `switch`, `date`, `textarea`, `button`.

**Display** (`golit.ui`) — `card`, `columns`, `grid`, `tabs`, `expander`, `accordion`, `divider`,
`metric`, `scorecard`, `alert`, `badge`, `progress`, `skeleton`, `spinner`, `table`, `markdown`,
`code`, `json_view`, `heading`, `caption`.

**Realtime** (`golit.ui`) — `chat`, `webcam`, `camera`, `recorder`.

```python
import golit.ui as ui

@app.view
def panel(by_region, total):
    return ui.card(
        ui.columns([ui.metric("Revenue", f"${total:,}", delta="+8%"), chart_fig]),
        title="Overview",
    )
```

Components compose through the renderer, so any argument can be a DataFrame, a chart figure, another
component, or trusted HTML. See
[`examples/components_gallery/app.py`](examples/components_gallery/app.py).

## Page layout

By default views stack under one controls panel. `golit.layout` arranges the reactive view fragments
into a sidebar, rows, tabs, etc. — the layout is static scaffold, so each view keeps its `id` and
still swaps in place on POST/SSE.

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

References are validated at build time: every `View`/`Control` must resolve to a real view/input and
be placed at most once.

## Deploying and scaling

A single process needs nothing extra. To scale horizontally, set `GOLIT_REDIS_URL` and run **N
single-worker instances behind a sticky (session-cookie) load balancer** — session state is
worker-local by design, and Redis fans server-side invalidations across the fleet. A runnable
podman/nginx stack lives in [`deploy/`](deploy/).

```bash
pip install "golit[redis]"
export GOLIT_REDIS_URL=redis://localhost:6379
golit run examples/sales_explorer/app.py
```

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for the full topology and why `uvicorn --workers` can't provide
session affinity.

## Architecture

| Tier | Role            | Technology                                                                      |
| ---- | --------------- | ------------------------------------------------------------------------------- |
| 0    | Reactive kernel | Rust + PyO3 (`src/`, `golit._golit`)                                             |
| 1    | Orchestrator    | Litestar + SSE/Redis fan-out (`golit.server`)                                    |
| 2    | Transport       | HTMX fragments; static SVG, interactive charts, native maps (`golit.rendering`) |
| 3    | Local shield    | Alpine.js (widget immediacy, tab state)                                          |

See [`project_scope.md`](project_scope.md) for the full architecture and
[`golit_benchmark.md`](golit_benchmark.md) for the benchmark methodology.

## Status

**v1.0.0 — first stable release** (see the [CHANGELOG](CHANGELOG.md)).

Built end-to-end and green (**17** cargo + **209** pytest, ruff + mypy clean): Rust kernel, reactive
engine, rendering (static **and** interactive charts, native MapLibre maps, auto-rendered Great
Tables), the `golit.ui` component library, page layout, DuckDB SQL nodes, GIS (vector maps + MVT
vector tiles for large data; single-band, RGB-composite, tiled-COG raster maps; WhiteboxTools
terrain; Earth Engine overlays; spatial SQL — `golit.gis`), Litestar server (POST + SSE), Redis
pub/sub fan-out, multi-worker deployment, live polled sources (`@app.poll`), realtime WebSocket chat,
video (server-side MJPEG streams + browser-camera CV), and audio (mic recorder), the benchmark
harness ([`bench/`](bench/), with measured Golit-vs-Dash results), and the examples.

**Deferred:** a standard-cloud-instance benchmark publication and the wider design suite in
`golit_pages/`.

## Development

```bash
make dev      # set up venv + build extension
make test     # cargo test + pytest
make lint     # ruff + mypy
make build    # release wheel
```

## License

Golit is released under the **Apache License 2.0**.
