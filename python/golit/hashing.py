"""Content hashing for memoization.

A node's *input signature* is a ``u64`` derived from the current values of its
dependencies. The kernel compares this hash against the one stored at the node's
last clean commit to decide whether to recompute (see ``Graph.needs_recompute``).

Hashes only need to be stable *within a single process run*, so Python's builtin
``hash`` (per-process stable) is fine for scalars; Polars frames/series get a
cheap structural+content hash.
"""

from __future__ import annotations

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


def hash_value(value: Any) -> int:
    """Hash a single value to a ``u64``."""
    if isinstance(value, pl.DataFrame):
        return _hash_dataframe(value)
    if isinstance(value, pl.Series):
        return _hash_series(value)
    if is_duckdb_relation(value):
        return _hash_dataframe(relation_to_polars(value))
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


def signature_hash(values: list[Any]) -> int:
    """Combine an ordered list of input values into one ``u64`` signature (FNV-1a
    over the per-value hashes)."""
    h = _FNV_OFFSET
    for value in values:
        h = ((h ^ hash_value(value)) * _FNV_PRIME) & _U64
    return h
