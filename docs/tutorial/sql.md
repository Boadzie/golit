# SQL nodes

Sometimes a transform is just easier to express in SQL. A Golit reactive node can be written as SQL instead of Polars — `golit.sql()` runs [DuckDB](https://duckdb.org/) in-process over your upstream frames and returns Polars, so the node memoizes and renders exactly like any other.

Install the extra:

```bash
pip install "golit[sql]"
```

This pulls in DuckDB and PyArrow. DuckDB is imported **lazily inside `sql()`**, never at framework import time — so installing Golit without the extra costs nothing.

## `golit.sql()`

```python
from golit import sql

sql(query, **frames)
```

Each keyword binds a name usable in the query; values may be Polars (or pandas / Arrow) frames. The result is fully materialized to a Polars `DataFrame`.

```python
import polars as pl
from golit import App, sql, slider, select


@app.reactive
def by_region(
    data: pl.DataFrame,
    threshold: int = slider(0, 200, default=40, label="Min revenue"),
    region: str = select(REGIONS, default="All", label="Region"),
) -> pl.DataFrame:
    where = f"revenue > {int(threshold)}"
    if region != "All":
        where += f" AND region = '{region}'"
    return sql(
        "SELECT region, sum(revenue)::BIGINT AS revenue "
        f"FROM d WHERE {where} GROUP BY region ORDER BY region",
        d=data,                              # bind the upstream frame as `d`
    )
```

The slider and select feed straight into the `WHERE` clause. Because the SQL node returns Polars, the chart and table downstream memoize and re-render like any Polars node — only when its result actually changes.

!!! tip "Why this is zero-copy and fast"
    DuckDB and Polars both speak Apache Arrow, so DuckDB reads the registered frames **without copying** and Golit gets Arrow back. You're not paying a serialization tax to "drop into SQL".

## Raw DuckDB relations also work

If you'd rather use DuckDB's own API, a `DuckDBPyRelation` returned from a node is auto-detected and materialized to Polars for hashing and rendering:

```python
import duckdb

@app.reactive
def summary(data):
    return duckdb.sql("SELECT region, count(*) AS n FROM data GROUP BY region")
```

You can also return a relation **straight from a view** — Golit renders it as a table, the same as a Polars frame.

## When to reach for it

`golit.sql()` shines for set-based aggregation, joins across several frames, and window functions that read cleanly in SQL. For row-wise expression work and column math, Polars' own API is usually tighter. They interop freely — mix and match per node.

The [`duckdb_sql`](https://github.com/boadzie/golit/tree/main/examples/duckdb_sql) example is a complete SQL-driven aggregation app.

## Next

The last tutorial step: **[Running your app](running.md)**.
