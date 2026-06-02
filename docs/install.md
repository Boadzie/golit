# Installation

## Requirements

Golit requires **Python 3.11 or newer**. Installing it pulls in a small set of core dependencies:

| Dependency | Role |
| --- | --- |
| [Litestar](https://litestar.dev/) | The async server that hosts your app (Tier 1). |
| [Polars](https://pola.rs/) | The columnar data engine; node values are Polars frames. |
| [Lets-Plot](https://lets-plot.org/) | Grammar-of-graphics charts rendered to static SVG. |
| [Uvicorn](https://www.uvicorn.org/) | The ASGI server `golit run` launches. |

The Rust reactive kernel ships **precompiled** in the wheel — you don't need a Rust toolchain to *use* Golit, only to build it from source.

## Install

```bash
pip install golit
```

Verify it:

```python
import golit

print(golit.__version__)        # the Python package version
print(golit.kernel_version())   # the compiled Rust kernel version
```

## Optional extras

Golit keeps the core install lean. Heavier or situational dependencies live behind **extras** you opt into — each is imported lazily, only when you actually use the feature.

=== "Interactive charts"

    ```bash
    pip install "golit[charts]"
    ```

    Pulls in **Plotly**, **Altair**, and **Bokeh**. Return one of their figures from a view and Golit renders it as an interactive, client-side chart. (AnyChart needs no Python package — it loads from a CDN.) See [Charts](tutorial/charts.md).

=== "SQL nodes"

    ```bash
    pip install "golit[sql]"
    ```

    Pulls in **DuckDB** and **PyArrow**. Lets you write reactive nodes as SQL over your Polars frames with [`golit.sql()`](tutorial/sql.md).

=== "Redis fan-out"

    ```bash
    pip install "golit[redis]"
    ```

    Pulls in the **redis** client. Needed only when scaling to multiple workers, where server-side invalidations fan out across the fleet. See [Deployment & scaling](advanced/deployment.md).

You can combine extras: `pip install "golit[charts,sql,redis]"`.

## Install from source

If you want to hack on Golit itself (including the Rust kernel), clone the repo and use the provided `Makefile`. It manages a [uv](https://docs.astral.sh/uv/)-backed virtualenv and builds the extension with [maturin](https://www.maturin.rs/):

```bash
git clone https://github.com/boadzie/golit
cd golit
make dev      # uv venv (3.11) + deps + build the Rust kernel
make test     # cargo test + pytest
```

See [Contributing](about/contributing.md) for the full developer workflow.

## Next

You're ready to build. Head to **[Your first app](tutorial/first-app.md)**.
