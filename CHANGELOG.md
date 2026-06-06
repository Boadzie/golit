# Changelog

All notable changes to Golit are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project adheres to
[Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-06-06

First stable release. Golit is a high-performance reactive **DAG** framework for Python —
*Streamlit, until it goes to production* — with a Rust kernel and a server-rendered HTMX
transport, where update cost is proportional to the change, not the program.

### Reactive core

- Rust + PyO3 reactive kernel: dirty tracking, topological scheduling, memoized propagation.
- `@app.source` / `@app.reactive` / `@app.view` — dependencies inferred from parameter names; a
  node re-executes only when an upstream node or input changes, and unchanged outputs cascade
  into memo hits (nothing on the wire).
- Per-session state (worker-local Polars values) over a shared, immutable topology.
- A larger app can be split across modules (one shared `App` instance + import-for-side-effects).

### Inputs & components

- Reactive input widgets: `slider`, `number`, `select`, `text`, `checkbox`, `upload`, `radio`,
  `multiselect`, `switch`, `date`, `textarea`, `button`.
- `golit.ui` — shadcn-styled, server-rendered builders: `card`, `columns`, `grid`, `tabs`,
  `expander`, `accordion`, `divider`, `metric`, `scorecard`, `alert`, `badge`, `progress`,
  `skeleton`, `spinner`, `table`, `markdown`, `code`, `json_view`, `heading`, `caption`.
- Page layout (`golit.layout`): a sidebar/rows/tabs scaffold, validated at build time.

### Rendering

- A view may return a `str` (trusted markup), a Polars `DataFrame`, a DuckDB relation, a chart,
  a map, a Great Tables `GT`, anything with `_repr_html_()`, a Matplotlib figure, or `bytes`.
- Charts: Lets-Plot static SVG; interactive **Plotly / Altair / Bokeh / AnyChart** that hydrate
  on load and across POST/SSE swaps; `chart_spec(lib, dict)` for the raw wire spec.
- Tables: return a `great_tables` **`GT`** object and Golit auto-renders its self-contained HTML;
  `ui.gt_theme` restyles it to match golit's surface. (`golit[tables]`)

### Maps & GIS (`golit.gis`)

- Native **MapLibre GL** maps from a GeoDataFrame; choropleths, tooltips, and DuckDB spatial SQL.
- MVT **vector tiles** for large vector data; single-band, RGB-composite, and tiled-COG **raster**
  maps; **WhiteboxTools** terrain analysis; **Google Earth Engine** overlays.

### Realtime

- **SSE** server-push channel with a pluggable pub/sub (in-memory single-node, **Redis** fleet).
- **Live data sources** — `@app.poll(name, interval)`: external data that changes on its own (a
  Google Sheet, an API) is fetched in the background and pushed on a content-hash change.
- **WebSocket chat** — `@app.on_message` + `ui.chat`.
- **Video** — server-side **MJPEG** streams (`@app.stream` + `ui.webcam`, with `shared=True`
  fan-out) and **browser-camera** computer vision (`@app.on_frame` + `ui.camera`).
- **Audio** — a microphone **recorder** (`@app.on_audio` + `ui.recorder`) with in-browser WAV
  capture, inline playback, and download.

### SQL

- `golit.sql(query, **frames)` — in-process **DuckDB** SQL over Polars frames as a reactive node.
  (`golit[sql]`)

### Server, deployment & tooling

- Litestar ASGI app via `create_app`; the `golit run app.py` CLI (uvicorn).
- Horizontal scale: N single-worker instances behind a sticky load balancer + Redis fan-out, with
  a `deploy/` compose stack and an automated, self-validating **cross-node fan-out verifier**.
- Optional extras: `charts`, `sql`, `gis` / `gis-raster` / `gis-tiles` / `gis-terrain` /
  `gis-ee` / `gis-vector-tiles`, `vision` / `vision-cv`, `tables`, `redis`.

### Quality

- 17 Rust + 209 Python tests; ruff + mypy clean; a benchmark harness (`bench/`) with measured
  Golit-vs-Dash results.

[1.0.0]: https://github.com/Boadzie/golit/releases/tag/v1.0.0
