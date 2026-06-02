"""Measurement primitives for B1.

The harness measures Golit's engine without touching it: timing happens at the
boundaries the engine already exposes.

* ``LEDGER`` — every generated node body (see :mod:`bench.gen_app`) is wrapped so
  it records *how long it ran* and *that it ran*. After a ``Session.update`` the
  ledger's ``exec_count`` is exactly the number of node functions the dirty
  subgraph actually executed — the cleanest possible proof that work is
  proportional to the change, not the graph.
* :func:`measure_update` — wall-clock of ``Session.update`` (the real server-side
  metric: input change → fragments ready), p50/p95/p99.
* :func:`measure_full` — wall-clock of a *full* graph recompute, the naive
  "rerun everything" upper bound a non-reactive framework pays.
* :func:`measure_schedule` — wall-clock of the pure Rust ``dirty_subgraph`` call,
  isolating the kernel's scheduling cost as the total graph grows.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np


class Ledger:
    """Accumulates executed-node count and execution time for one measurement."""

    __slots__ = ("exec_ns", "exec_count")

    def __init__(self) -> None:
        self.exec_ns = 0
        self.exec_count = 0

    def reset(self) -> None:
        self.exec_ns = 0
        self.exec_count = 0


LEDGER = Ledger()


def timed_body(work: Callable[[dict[str, Any]], Any]) -> Callable[[dict[str, Any]], Any]:
    """Wrap a node body so each execution is recorded in :data:`LEDGER`."""

    def run(kwargs: dict[str, Any]) -> Any:
        t0 = time.perf_counter_ns()
        out = work(kwargs)
        LEDGER.exec_ns += time.perf_counter_ns() - t0
        LEDGER.exec_count += 1
        return out

    return run


def percentiles(samples_ns: list[int]) -> dict[str, float]:
    """Summarize nanosecond samples as microseconds (p50/p95/p99/mean + n)."""
    a = np.asarray(samples_ns, dtype=float) / 1000.0  # ns -> us
    return {
        "p50_us": float(np.percentile(a, 50)),
        "p95_us": float(np.percentile(a, 95)),
        "p99_us": float(np.percentile(a, 99)),
        "mean_us": float(a.mean()),
        "n": len(a),
    }


def measure_update(
    session: Any,
    input_id: str,
    values: list[Any],
    *,
    warmup: int,
    iters: int,
) -> tuple[dict[str, float], int]:
    """Time ``session.update(input_id, …)`` over ``iters`` runs.

    ``values`` are cycled (continuously across warmup → measurement, so the first
    measured value still differs from the last warmup value) — every update
    commits a *different* input value, a genuine recompute, never a memo hit.
    Returns the latency summary and the per-update executed-node count.
    """
    n = len(values)
    idx = 0
    for _ in range(warmup):
        session.update(input_id, values[idx % n])
        idx += 1

    samples: list[int] = []
    exec_count = 0
    for _ in range(iters):
        v = values[idx % n]
        idx += 1
        LEDGER.reset()
        t0 = time.perf_counter_ns()
        session.update(input_id, v)
        samples.append(time.perf_counter_ns() - t0)
        exec_count = max(exec_count, LEDGER.exec_count)
    return percentiles(samples), exec_count


def measure_full(session: Any, *, warmup: int, iters: int) -> dict[str, float]:
    """Time a full graph recompute (``initial_render`` forces every node)."""
    for _ in range(warmup):
        session.initial_render()

    samples: list[int] = []
    for _ in range(iters):
        t0 = time.perf_counter_ns()
        session.initial_render()
        samples.append(time.perf_counter_ns() - t0)
    return percentiles(samples)


def measure_schedule(graph: Any, seeds: list[str], *, warmup: int, iters: int) -> dict[str, float]:
    """Time the pure Rust ``dirty_subgraph`` scheduling call in isolation."""
    for _ in range(warmup):
        graph.dirty_subgraph(seeds)

    samples: list[int] = []
    for _ in range(iters):
        t0 = time.perf_counter_ns()
        graph.dirty_subgraph(seeds)
        samples.append(time.perf_counter_ns() - t0)
    return percentiles(samples)
