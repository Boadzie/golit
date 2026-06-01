# Golit

> **Streamlit, until it goes to production.**

A high-performance **Reactive Directed Acyclic Graph (DAG)** framework for Python.
Golit maps your data dependencies, then on every interaction recomputes only the
nodes that changed — not your whole script. Rust reactive core, Polars data,
server-rendered SVG charts, HTMX fragment transport.

> 🚧 Early development. See [`project_scope.md`](project_scope.md) for the vision
> and [`golit_benchmark.md`](golit_benchmark.md) for the benchmark methodology.

## Quickstart

```bash
make dev     # uv venv (3.11) + deps + build the Rust kernel
make test    # cargo test + pytest
make run     # launch the example app
```

## How it works

Nodes are plain Python functions; dependencies are inferred from parameter names.

```python
import polars as pl
from golit import App, slider, upload

app = App(title="Sales Explorer")

@app.source
def data(file=upload("Upload CSV")) -> pl.DataFrame:
    return pl.read_csv(file)

@app.reactive
def filtered(data: pl.DataFrame, threshold: int = slider(0, 100, default=20)) -> pl.DataFrame:
    return data.filter(pl.col("revenue") > threshold)

@app.view
def chart(filtered: pl.DataFrame):
    return ggplot(filtered, aes("region", "revenue")) + geom_bar(stat="identity")
```

Moving the slider dirties `threshold → filtered → chart`. The `data` node is never
touched; only the `chart` fragment is re-rendered and swapped.
