"""Synthetic Streamlit app — the behavioral twin of ``bench.gen_app.make_app``.

Same shape as the Golit synthetic app: a cached data load, a slider that drives a
``filter -> transform chain -> chart``, and ``unaffected`` aggregations that depend
only on the data (never on the slider). Graph shape from the environment:
``GOLIT_BENCH_ROWS`` / ``_DEPTH`` / ``_UNAFFECTED``.

**The fair fight.** Caching is enabled the way a competent Streamlit dev would
write it — ``@st.cache_data`` on the expensive *shared* work (the data load and
the independent aggregations), so on a rerun those are cache *hits*. The one thing
left uncached is the chain the active widget drives, because that genuinely must
recompute on every interaction (it does in Golit too). This is Streamlit's best
case; the unaffected aggregations even take only small int args, so their
cache-key hashing is trivial. The benchmark still measures what Streamlit cannot
avoid: re-running the whole script — *touching every node* — on every interaction.
"""

from __future__ import annotations

import os

import numpy as np
import polars as pl
import streamlit as st

ROWS = int(os.environ.get("GOLIT_BENCH_ROWS", "100000"))
DEPTH = int(os.environ.get("GOLIT_BENCH_DEPTH", "3"))
UNAFFECTED = int(os.environ.get("GOLIT_BENCH_UNAFFECTED", "0"))


@st.cache_data
def load_data(rows: int) -> pl.DataFrame:
    rng = np.random.default_rng(0)
    v = rng.integers(0, 100, size=rows)
    return pl.DataFrame({"v": v, "g": v % 16})


@st.cache_data
def unaffected_agg(rows: int, j: int) -> int:
    """Depends only on the data, never the slider — a cache hit on every rerun.
    Small int args keep the cache-key hashing trivial (Streamlit's best case)."""
    df = load_data(rows)
    return int(df.group_by("g").agg(pl.col("v").sum())["v"].sum())


def affected(data: pl.DataFrame, threshold: int, depth: int) -> pl.DataFrame:
    """The slider-driven chain — uncached, so it recomputes each rerun, like Golit's
    dirty subgraph does."""
    df = data.filter(pl.col("v") > threshold)
    for _ in range(depth - 1):
        df = df.with_columns((pl.col("v") + 1).alias("v"))
    return df


data = load_data(ROWS)  # cache hit after the first run
threshold = st.slider("threshold", 0, 100, 10)
out = affected(data, threshold, DEPTH)
st.markdown(f"rows={out.height}")  # the 'chart' fragment

# Every rerun re-touches all unaffected nodes — cheap cache hits, but O(unaffected)
# calls Streamlit cannot skip. This is the climb the hero chart captures.
for _j in range(UNAFFECTED):
    unaffected_agg(ROWS, _j)
