"""Content hashing for memoization.

A node's *input signature* is a ``u64`` the kernel compares against the one stored
at the node's last clean commit to decide whether to recompute (see
``Graph.needs_recompute``). The kernel folds that signature in Rust (see
``Graph.check_node``) from two kinds of part:

* **scalar input values** — hashed by content via :func:`hash_value`, pushed to the
  kernel on each change (``Graph.commit_input``). Cheap, and it catches a control
  reverting to a previous value (a genuine memo hit).
* **upstream node outputs** — referenced by *epoch*, not content (see
  :class:`golit.registry.Registry`). Content-hashing a frame is O(rows) and, for a
  cheap node, dwarfs the recompute it guards; an epoch compare is O(1).

This module supplies the Python-side half: :func:`hash_value` for the scalar (and
the rare frame-valued *input* — a widget default) content hashes, and :func:`combine`,
the FNV-1a fold that mirrors the kernel's ``combine_hashes`` exactly.

Hashes only need to be stable *within a single process run*, so Python's builtin
``hash`` (per-process stable) is fine for scalars.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import polars as pl

from .data import is_duckdb_relation, relation_to_polars

_U64 = (1 << 64) - 1
_FNV_OFFSET = 1469598103934665603
_FNV_PRIME = 1099511628211


def _hash_dataframe(df: pl.DataFrame) -> int:
    schema = tuple((name, str(dtype)) for name, dtype in df.schema.items())
    content = int(df.hash_rows().sum()) if df.height else 0
    return hash((schema, df.shape, content)) & _U64


def _hash_series(s: pl.Series) -> int:
    content = int(s.hash().sum()) if len(s) else 0
    return hash((s.name, str(s.dtype), len(s), content)) & _U64


def _is_geodataframe(value: Any) -> bool:
    cls = type(value)
    return cls.__name__ == "GeoDataFrame" and (cls.__module__ or "").startswith("geopandas")


def _hash_geodataframe(gdf: Any) -> int:
    """Content-hash a GeoDataFrame: the geometry as WKB bytes plus the attribute
    columns. Belt-and-suspenders for a geo-valued *widget default*; node outputs stay on
    epochs (see the module docstring), so this is off the hot path."""
    geom = gdf.geometry.name
    wkb = b"".join(b if b is not None else b"" for b in gdf.geometry.to_wkb())
    attributes = gdf.drop(columns=[geom])
    try:
        attrs = _hash_dataframe(pl.from_pandas(attributes))
    except Exception:  # noqa: BLE001 - any exotic attribute dtype falls back to repr
        attrs = hash(repr(attributes.values.tolist())) & _U64
    return hash((hash(wkb) & _U64, attrs)) & _U64


def hash_value(value: Any) -> int:
    """Hash a single value to a ``u64``."""
    if isinstance(value, pl.DataFrame):
        return _hash_dataframe(value)
    if isinstance(value, pl.Series):
        return _hash_series(value)
    if is_duckdb_relation(value):
        return _hash_dataframe(relation_to_polars(value))
    if _is_geodataframe(value):
        return _hash_geodataframe(value)
    if isinstance(value, (bytes, bytearray)):
        return hash(bytes(value)) & _U64
    if hasattr(value, "getvalue"):  # BytesIO and friends — hash the buffer
        try:
            return hash(value.getvalue()) & _U64
        except Exception:  # noqa: BLE001 - fall through to repr
            pass
    try:
        return hash(value) & _U64
    except TypeError:
        return hash(repr(value)) & _U64


def combine(parts: Iterable[int]) -> int:
    """Fold ordered ``u64`` parts (content hashes and/or epochs) into one signature
    via FNV-1a. The engine mixes scalar content hashes with upstream node epochs."""
    h = _FNV_OFFSET
    for part in parts:
        h = ((h ^ (part & _U64)) * _FNV_PRIME) & _U64
    return h
