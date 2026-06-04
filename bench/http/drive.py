"""The client-side load driver — one sequential session hammering one input.

Reused by the rival-framework harnesses later: anything exposing an HTTP endpoint
that takes a committed value and returns the updated fragment plugs in here.
"""

from __future__ import annotations

import json
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


def measure_dash_http(
    base_url: str,
    values: list,
    *,
    warmup: int,
    iters: int,
    timeout: float = 120.0,
    output_id: str = "chart",
    input_id: str = "threshold",
) -> dict[str, float]:
    """Drive Dash's **real** callback endpoint, the analog of ``measure_http_update``.

    A slider move in a browser is a ``POST /_dash-update-component`` whose JSON body
    names the changed input and the wanted output; Flask routes it, sets up
    ``callback_context``, runs the callback (chain + build the Plotly figure), and
    returns the figure JSON. Timing that round-trip over loopback folds in everything
    the direct-call floor skipped — Flask, input deserialization, figure serialization.
    ``values`` cycle so every POST is a genuine recompute. ``output_id``/``input_id``
    select the callback's chart and slider (the memo twin uses ``chart_a``/``threshold_a``).
    Returns the e2e latency summary plus mean response ``bytes``."""
    def body(value: int) -> str:
        return json.dumps({
            "output": f"{output_id}.figure",
            "outputs": {"id": output_id, "property": "figure"},
            "inputs": [{"id": input_id, "property": "value", "value": value}],
            "changedPropIds": [f"{input_id}.value"],
        })

    headers = {"content-type": "application/json"}
    with httpx.Client(timeout=timeout, headers=headers) as client:
        n = len(values)
        idx = 0
        for _ in range(warmup):
            client.post(f"{base_url}/_dash-update-component", content=body(values[idx % n]))
            idx += 1

        samples: list[int] = []
        sizes: list[int] = []
        for _ in range(iters):
            v = values[idx % n]
            idx += 1
            t0 = time.perf_counter_ns()
            r = client.post(f"{base_url}/_dash-update-component", content=body(v))
            samples.append(time.perf_counter_ns() - t0)
            r.raise_for_status()
            sizes.append(len(r.content))

    summary = percentiles(samples)
    summary["bytes"] = round(sum(sizes) / len(sizes), 1)
    return summary
