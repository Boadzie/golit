# Contributing

Golit is a Rust + Python project. This page gets you from a clone to a green test run, the docs building locally, and a clean change.

## Prerequisites

- **Python 3.11+**
- **A Rust toolchain** (stable) — needed to build the kernel. [rustup](https://rustup.rs/) is the easy path.
- **[uv](https://docs.astral.sh/uv/)** — manages the virtualenv and dependencies.

## Set up

```bash
git clone https://github.com/boadzie/golit
cd golit
make dev
```

`make dev` creates a uv venv pinned to Python 3.11, installs dependencies, and builds the Rust extension as an editable install with [maturin](https://www.maturin.rs/).

## The workflow

```bash
make test     # cargo test + pytest
make lint     # ruff + mypy
make run      # serve examples/sales_explorer/app.py
make build    # release wheel
```

`make test` runs both halves:

- **`make test-rust`** — `cargo test` over the pure-Rust kernel logic in `src/core.rs`.
- **`make test-py`** — rebuilds the extension and runs `pytest`.

!!! warning "`cargo test` needs the venv's Python"
    The abi3 floor is Python 3.11, but a system Python may be older. The Makefile sets `PYO3_PYTHON=.venv/bin/python` for `cargo test` so the kernel links against the right interpreter. If you run `cargo test` by hand, set that variable yourself.

## Repository layout

```text
src/                    # Rust reactive kernel
  core.rs               #   pure logic (dirty tracking, topo schedule, memo) — cargo-tested
  lib.rs                #   thin PyO3 wrapper → golit._golit
python/golit/           # the Python package
  app.py                #   App blueprint + @source/@reactive/@view
  nodes.py              #   signature introspection → node defs
  engine.py             #   Session: the per-client scheduler driver
  registry.py           #   per-session value store (= the memo cache)
  hashing.py            #   content hashing for memoization
  widgets.py            #   input widgets + factories
  data.py               #   golit.sql() (DuckDB)
  charts.py             #   Lets-Plot re-exports + anychart
  ui.py                 #   golit.ui presentational components
  layout.py             #   golit.layout page layout
  rendering/            #   value → HTML, the page shell, chart mounts
  server/               #   Litestar factory, routes, sessions, SSE, pub/sub
  cli.py                #   `golit run`
tests/                  # pytest suite
examples/               # runnable example apps
deploy/                 # podman/docker + nginx scaling stack
docs/                   # this documentation (MkDocs Material)
```

## Building the docs

The docs are [MkDocs Material](https://squidfunk.github.io/mkdocs-material/) with [mkdocstrings](https://mkdocstrings.github.io/) for the API reference. Install the docs dependency group and serve with live reload:

```bash
uv sync --group docs        # or: pip install -r requirements (see pyproject [dependency-groups].docs)
uv run mkdocs serve         # http://127.0.0.1:8000
uv run mkdocs build         # static site into site/
```

The reference pages render from the live docstrings, so **keep docstrings accurate** — they're the API reference. A `make docs` / `make docs-serve` target wraps these.

## Code style

- **Python:** ruff (line length 100; rules `E,F,I,UP,B`) and mypy must pass. Widgets-as-defaults are intentional, so `B008` is disabled project-wide.
- **Rust:** keep the kernel logic in `core.rs` pure and unit-tested; `lib.rs` only marshals types and maps errors.
- **Commits:** small and focused — one logical change per commit, conventional-commit style (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).

## A good change

1. A test that covers it (`cargo test` for kernel logic, `pytest` for Python).
2. `make test` and `make lint` green.
3. Docstrings updated if you touched a public symbol (the reference depends on them).
4. A focused commit with a clear message.
