# Golit

> **Streamlit, until it goes to production.**

A high-performance **Reactive Directed Acyclic Graph (DAG)** framework for Python.
Golit maps your data dependencies, then on every interaction recomputes only the
nodes that changed — not your whole script.

- **Rust reactive kernel** (PyO3) — dirty tracking, topological scheduling, propagation
- **Polars** data, held Python-side; only node ids/hashes cross the FFI boundary
- **Litestar** orchestration; **HTMX** server-rendered fragment transport (no client framework)
- **Lets-Plot** → static server-rendered **SVG** charts
- **SSE** push channel with a pluggable pub/sub (in-memory now; Redis-ready interface)
- **Tailwind + shadcn-styled** HTML, server-rendered (the `golit_pages` design system)

See [`project_scope.md`](project_scope.md) for the architecture and
[`golit_benchmark.md`](golit_benchmark.md) for the benchmark methodology.

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

## Architecture (tiers)

| Tier | Role | Tech |
| ---- | ---- | ---- |
| 0 | Reactive kernel | Rust + PyO3 (`src/`, `golit._golit`) |
| 1 | Orchestrator | Litestar (`golit.server`) |
| 2 | Transport | HTMX fragments + Lets-Plot SVG (`golit.rendering`) |
| 3 | Local shield | Alpine.js (widget immediacy) |

## Status

Single-node framework, built end-to-end: Rust kernel, Python reactive engine,
rendering, Litestar server (POST + SSE), and the example app. **Deferred:** the
Redis pub/sub implementation (interface in place), multi-worker scaling, the
benchmark harness, and the wider design suite.

## Development

```bash
make dev      # set up venv + build extension
make test     # cargo test + pytest
make lint     # ruff + mypy
make build    # release wheel
```
