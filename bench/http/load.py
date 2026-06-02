"""Concurrent closed-loop load driver for B2 (concurrency scaling).

``C`` virtual users hammer the server at once. Each user owns its own
``httpx.AsyncClient`` — a distinct cookie jar, hence a distinct Golit **session**
(its own worker-local Polars state). A user runs closed-loop: ``GET /`` once to
establish the session, then POSTs updates back-to-back until the shared window
closes. We aggregate every user's per-request latency over the window and report
p50/p95/p99 plus achieved throughput (requests/second).

**The load is generated across multiple OS processes.** A single-process asyncio
client tops out around a few thousand req/s and would itself become the bottleneck —
making a faster/horizontally-scaled server look like it didn't scale. So the users
are split over ``min(C, cpu_count)`` worker processes that share one wall-clock
window; the server, not the driver, is what saturates.

A user is pinned to a single base URL for its whole life. With one URL that's just
load on one instance; with several (N sticky instances) it models a cookie-hash load
balancer — each session stays on the instance holding its state, which is exactly
Golit's scale model (worker-local frames, no shared session store).
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import os
import time

import httpx

from ..instrument import percentiles

_START_LEAD_S = 1.0  # head start so every spawned process is looping before the window


async def _user(
    base_url: str, input_id: str, values: list, *, warm_wall: float, end_wall: float, store: list
) -> None:
    async with httpx.AsyncClient(timeout=120.0) as client:
        (await client.get(f"{base_url}/")).raise_for_status()  # establish session
        n = len(values)
        idx = 0
        lat: list[int] = []
        while time.time() < end_wall:
            v = values[idx % n]
            idx += 1
            t0 = time.perf_counter_ns()
            r = await client.post(f"{base_url}/node/{input_id}", data={"value": v})
            dt = time.perf_counter_ns() - t0
            r.raise_for_status()
            if time.time() >= warm_wall:  # count only requests sent inside the window
                lat.append(dt)
        store.append(lat)


async def _drive(
    base_urls: list[str], input_id: str, values: list, user_idxs: list[int],
    start_wall: float, warm_wall: float, end_wall: float,
) -> list[int]:
    delay = start_wall - time.time()
    if delay > 0:
        await asyncio.sleep(delay)  # align to the shared window
    store: list[list[int]] = []
    await asyncio.gather(*[
        _user(base_urls[i % len(base_urls)], input_id, values,
              warm_wall=warm_wall, end_wall=end_wall, store=store)
        for i in user_idxs
    ])
    return [dt for lat in store for dt in lat]


def _proc_main(base_urls, input_id, values, user_idxs, start_wall, warm_wall, end_wall, q) -> None:
    q.put(asyncio.run(_drive(base_urls, input_id, values, user_idxs,
                             start_wall, warm_wall, end_wall)))


def measure_concurrent(
    base_urls: list[str], input_id: str, values: list,
    *, concurrency: int, warmup_s: float, measure_s: float, processes: int | None = None,
) -> dict[str, float]:
    """Run ``concurrency`` users (spread over worker processes) for ``measure_s``
    after ``warmup_s``; return latency percentiles (µs) + throughput (req/s)."""
    procs_n = processes or min(concurrency, max(1, os.cpu_count() or 2))
    buckets: list[list[int]] = [[] for _ in range(procs_n)]
    for i in range(concurrency):
        buckets[i % procs_n].append(i)
    buckets = [b for b in buckets if b]

    start_wall = time.time() + _START_LEAD_S
    warm_wall = start_wall + warmup_s
    end_wall = warm_wall + measure_s

    ctx = mp.get_context("spawn")
    q: mp.Queue = ctx.Queue()
    running = []
    for b in buckets:
        p = ctx.Process(
            target=_proc_main,
            args=(base_urls, input_id, values, b, start_wall, warm_wall, end_wall, q),
        )
        p.start()
        running.append(p)

    samples: list[int] = []
    for _ in running:  # drain before join so a large result can't deadlock the pipe
        samples.extend(q.get())
    for p in running:
        p.join()

    if not samples:
        return {"p50_us": 0.0, "p95_us": 0.0, "p99_us": 0.0, "mean_us": 0.0,
                "n": 0, "throughput_rps": 0.0}
    summary = percentiles(samples)
    summary["throughput_rps"] = round(len(samples) / measure_s, 1)
    return summary
