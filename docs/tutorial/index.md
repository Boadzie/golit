# Tutorial — User Guide

This guide teaches Golit step by step. Each page builds on the last, and almost every section is a small program you can copy, run, and poke at.

If you've used Streamlit or Dash, the *feel* will be familiar — you write Python, you get a UI. What's different is the execution model underneath, and a few pages in you'll start to rely on it.

## How to read this

The chapters are ordered. If you're new, go top to bottom:

1. **[Your first app](first-app.md)** — the smallest thing that runs.
2. **[The reactive graph](the-graph.md)** — sources, reactives, views, and how dependencies are inferred. *This is the core mental model.*
3. **[Inputs & widgets](inputs.md)** — the controls users interact with.
4. **[Views & rendering](views.md)** — what a view can return and how it becomes HTML.
5. **[Charts](charts.md)**, **[UI components](ui-components.md)**, **[Page layout](layout.md)**, **[SQL nodes](sql.md)** — the surface area.
6. **[Running your app](running.md)** — the CLI and the ASGI entry point.

## Running the examples

Every runnable example assumes you've installed Golit:

```bash
pip install golit
```

Save the code to a file — say `app.py` — and serve it:

```bash
golit run app.py
```

Then open <http://127.0.0.1:8000>.

!!! tip "The repo ships complete examples"
    Each topic here has a full, runnable counterpart under [`examples/`](https://github.com/boadzie/golit/tree/main/examples) in the source tree: `sales_explorer`, `charts_gallery`, `components_gallery`, and `duckdb_sql`. When a page references one, that's the file to open next.

When you're ready to understand *why* it's fast, the **[Concepts](../concepts/index.md)** section explains the reactive model and the architecture.
