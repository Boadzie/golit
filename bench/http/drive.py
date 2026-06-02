"""The client-side load driver — one sequential session hammering one input.

Reused by the rival-framework harnesses later: anything exposing an HTTP endpoint
that takes a committed value and returns the updated fragment plugs in here.
"""

from __future__ import annotations

import time

import httpx

from ..instrument import percentiles


def measure_http_update(
    base_url: str,
    input_id: str,
    values: list,
    *,
    warmup: int,
    iters: int,
    timeout: float = 120.0,
) -> dict[str, float]:
    """Drive ``POST {base_url}/node/{input_id}`` and time each round-trip.

    A single client with a persistent cookie jar holds one session (GET ``/``
    establishes it and triggers the one-time initial render). ``values`` are
    cycled continuously so every POST commits a different value — a genuine dirty
    subgraph, never a memo hit. Returns the end-to-end latency summary plus
    ``bytes`` (mean response-body size per update — the B3 number).
    """
    with httpx.Client(timeout=timeout) as client:
        client.get(f"{base_url}/").raise_for_status()  # session cookie + warm render

        n = len(values)
        idx = 0
        for _ in range(warmup):
            client.post(f"{base_url}/node/{input_id}", data={"value": values[idx % n]})
            idx += 1

        samples: list[int] = []
        sizes: list[int] = []
        for _ in range(iters):
            v = values[idx % n]
            idx += 1
            t0 = time.perf_counter_ns()
            r = client.post(f"{base_url}/node/{input_id}", data={"value": v})
            samples.append(time.perf_counter_ns() - t0)
            r.raise_for_status()
            sizes.append(len(r.content))

    summary = percentiles(samples)
    summary["bytes"] = round(sum(sizes) / len(sizes), 1)
    return summary
