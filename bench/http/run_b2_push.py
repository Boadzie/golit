"""B2-push — does a heavy update on one session stall *other* sessions' push channel?

``run_b2.py`` measures homogeneous POST throughput. By construction it cannot see
head-of-line blocking: every request is the same heavy update, so there is no quiet
co-located work to protect, and the saturation ceiling is identical whether the update
runs on the event loop or in a thread. That is exactly why it neither validates nor
refutes the ``to_thread`` offload (see its headline: a ~10% single-request tax, no
change to the knee).

This probe adds the piece Golit's architecture *guarantees*: every session holds a
long-lived ``GET /events`` SSE stream on the worker. The stream's keepalive is a pure
event-loop timer (``sse.py``: ``await wait_for(queue.get(), ping_interval)``), so the
interval a **quiet** subscriber sees between pings is a direct readout of event-loop
responsiveness — no recompute on that path at all.

Setup: one quiet SSE subscriber samples its ping inter-arrival gaps while ``C`` *other*
sessions hammer ``POST /node/threshold`` (a real Polars update) on the same instance,
under two server configs:

* **offload ON**  — updates run in a worker thread (production default); the loop stays
  free, so a quiet session's pings keep cadence.
* **offload OFF** — updates run inline on the loop (``GOLIT_NO_OFFLOAD=1``); a heavy
  update blocks the loop, delaying every other session's push.

The decisive variable is **per-update cost**, so we sweep dataset ``rows``. Inline
blocking can only stall the loop for *one update's wall time*, so:

* at a light update (~2ms, 100K rows) ON and OFF cadence are within noise — the offload
  is ~10% tax for no visible gain (matches ``run_b2.py``);
* at a heavy update (~tens of ms, 2M rows) OFF push-cadence p99 roughly *doubles* while
  ON holds near the floor — and ON also sustains far higher update throughput, because
  heavy Polars releases the GIL so the thread pool parallelises what the single loop
  thread serialises.

That asymmetry — cheap insurance at the light end, large saving at the heavy end — is
the case for keeping the offload. A no-load row gives the cadence floor. Writes
``results/b2_push.csv``::

    uv run --no-sync python -m bench.http.run_b2_push
    uv run --no-sync python -m bench.http.run_b2_push --quick
"""

from __future__ import annotations

import argparse
import csv
import os
import threading
import time

import httpx

from ..instrument import percentiles
from .serverctl import boot, free_port, stop, wait_ready

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
_SLIDER_VALUES = [11, 23, 37, 53, 71]
PING_INTERVAL_S = 0.05  # 50ms keepalive: fine enough to read loop stalls in the tail
FIELDS = ["scenario", "offload", "rows", "concurrency", "ping_ms", "gap_p50_ms",
          "gap_p95_ms", "gap_p99_ms", "gap_max_ms", "n", "load_rps"]


def _log(name: str) -> str:
    return os.path.join(RESULTS_DIR, f"b2push_{name}.log")


def _boot_server(port: int, *, offload: bool, rows: int, log_name: str):
    """Boot one bench instance with the SSE ping cadence and offload mode chosen via
    env. ``serverctl.boot`` copies ``os.environ``, so set the knobs here first."""
    os.environ["GOLIT_SSE_PING_INTERVAL"] = str(PING_INTERVAL_S)
    if offload:
        os.environ.pop("GOLIT_NO_OFFLOAD", None)
    else:
        os.environ["GOLIT_NO_OFFLOAD"] = "1"
    return boot(rows, 3, 0, port, _log(log_name))


def _probe(base_url: str, *, end_wall: float, pings: list[int]) -> None:
    """A quiet subscriber: open the SSE stream and timestamp each keepalive ping.

    Runs in its own thread with a blocking client so other client-side work can't
    perturb the arrival times we attribute to the *server's* loop."""
    with httpx.Client(timeout=120.0) as client:
        client.get(f"{base_url}/").raise_for_status()  # establish this session
        with client.stream("GET", f"{base_url}/events") as r:
            for line in r.iter_lines():
                if line.startswith(":"):  # a keepalive comment == one ping
                    pings.append(time.perf_counter_ns())
                if time.time() >= end_wall:
                    break


def _load_user(base_url: str, *, go: threading.Event, end_wall: float) -> list[int]:
    """One heavy-update session: establish before the window, then POST flat out."""
    sent = 0
    with httpx.Client(timeout=120.0) as client:
        client.get(f"{base_url}/").raise_for_status()  # warm the session pre-window
        go.wait()
        idx = 0
        while time.time() < end_wall:
            v = _SLIDER_VALUES[idx % len(_SLIDER_VALUES)]
            idx += 1
            client.post(f"{base_url}/node/threshold", data={"value": v}).raise_for_status()
            sent += 1
    return [sent]


def _measure(base_url: str, *, concurrency: int, warmup_s: float, measure_s: float) -> dict:
    """Sample ping gaps over ``measure_s`` while ``concurrency`` sessions POST.

    The probe streams for the whole window; ``concurrency`` load threads establish
    their sessions, block on ``go``, then POST during the measured window. Only pings
    that land inside the window are counted, so the floor isn't diluted by the idle
    warmup. ``concurrency == 0`` is the no-load cadence floor."""
    base = time.time()
    warm_wall = base + warmup_s
    end_wall = warm_wall + measure_s

    pings: list[int] = []
    probe = threading.Thread(target=_probe, args=(base_url,),
                             kwargs={"end_wall": end_wall, "pings": pings})
    probe.start()

    go = threading.Event()
    counts: list[list[int]] = []
    load: list[threading.Thread] = []
    for _ in range(concurrency):
        out: list[int] = []
        counts.append(out)
        t = threading.Thread(
            target=lambda o=out: o.extend(_load_user(base_url, go=go, end_wall=end_wall)))
        t.start()
        load.append(t)

    # Let the probe gather a beat of baseline, then open the load window.
    time.sleep(max(0.0, warm_wall - time.time()))
    warm_ns = time.perf_counter_ns()
    go.set()

    probe.join()
    for t in load:
        t.join()

    window = [p for p in pings if p >= warm_ns]
    gaps = [b - a for a, b in zip(window, window[1:], strict=False)]
    summary = percentiles(gaps) if gaps else {"p50_us": 0.0, "p95_us": 0.0,
                                              "p99_us": 0.0, "mean_us": 0.0, "n": 0}
    summary["max_us"] = max(gaps) / 1000.0 if gaps else 0.0
    sent = sum(c[0] for c in counts if c)
    return {"gaps": summary, "load_rps": round(sent / measure_s, 1)}


def run(*, rows_levels: list[int], concurrency: int, warmup_s: float,
        measure_s: float) -> list[dict]:
    """For each dataset size, measure the cadence floor (no load) plus the under-load
    cadence with offload on and off. Update cost scales with ``rows``; the offload only
    earns its keep once a single update is long enough to stall the loop between pings."""
    out: list[dict] = []
    for rows in rows_levels:
        scenarios = [
            ("no load (floor)", True, 0),
            ("under load", True, concurrency),
            ("under load", False, concurrency),
        ]
        for scenario, offload, c in scenarios:
            port = free_port()
            tag = f"{rows}_{'on' if offload else 'off'}_{c}"
            proc, log = _boot_server(port, offload=offload, rows=rows, log_name=tag)
            try:
                wait_ready(port, proc, _log(tag))
                m = _measure(f"http://127.0.0.1:{port}", concurrency=c,
                             warmup_s=warmup_s, measure_s=measure_s)
            finally:
                stop(proc, log)
            g = m["gaps"]
            out.append({
                "scenario": scenario, "offload": "on" if offload else "off", "rows": rows,
                "concurrency": c, "ping_ms": round(PING_INTERVAL_S * 1000, 1),
                "gap_p50_ms": round(g["p50_us"] / 1000, 2),
                "gap_p95_ms": round(g["p95_us"] / 1000, 2),
                "gap_p99_ms": round(g["p99_us"] / 1000, 2),
                "gap_max_ms": round(g["max_us"] / 1000, 2),
                "n": g["n"], "load_rps": m["load_rps"]})
    return out


def _headline(rows: list[dict]) -> str:
    lines: list[str] = []
    levels = sorted({r["rows"] for r in rows})
    for lvl in levels:
        sub = {(r["scenario"], r["offload"]): r for r in rows if r["rows"] == lvl}
        on, off = sub.get(("under load", "on")), sub.get(("under load", "off"))
        if not (on and off):
            continue
        factor = off["gap_p99_ms"] / max(on["gap_p99_ms"], 1e-9)
        lines.append(
            f"{lvl:>9,} rows: offload ON push-cadence p99 {on['gap_p99_ms']:6.1f}ms "
            f"vs OFF {off['gap_p99_ms']:6.1f}ms (max {off['gap_max_ms']:.0f}ms) "
            f"-> {factor:.1f}x worse inline on the loop.")
    return ("Quiet SSE push cadence under heavy concurrent updates (nominal "
            f"{rows[0]['ping_ms']:.0f}ms ping):\n  " + "\n  ".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description="Golit B2-push: SSE cadence under heavy load")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--rows", default="100000,2000000",
                    help="comma-separated dataset sizes (per-update cost) to sweep")
    ap.add_argument("--measure-s", type=float, default=5.0)
    ap.add_argument("--warmup-s", type=float, default=1.5)
    ap.add_argument("--out", default=os.path.join(RESULTS_DIR, "b2_push.csv"))
    args = ap.parse_args()

    concurrency, measure_s, warmup_s = (
        (4, 2.5, 1.0) if args.quick else (args.concurrency, args.measure_s, args.warmup_s))
    rows_levels = [int(x) for x in args.rows.split(",")]

    os.makedirs(RESULTS_DIR, exist_ok=True)
    print(f"B2-push: SSE ping cadence under load — rows={rows_levels} C={concurrency} "
          f"ping={PING_INTERVAL_S * 1000:.0f}ms measure={measure_s}s\n")

    t0 = time.perf_counter()
    rows = run(rows_levels=rows_levels, concurrency=concurrency,
               warmup_s=warmup_s, measure_s=measure_s)
    elapsed = time.perf_counter() - t0

    for r in rows:
        tag = (f"{r['rows']:>9,}r {r['scenario']:<16} "
               f"offload={r['offload']:<3} C={r['concurrency']}")
        print(f"  {tag}  gap p50={r['gap_p50_ms']:6.2f}ms p95={r['gap_p95_ms']:6.2f}ms "
              f"p99={r['gap_p99_ms']:6.2f}ms max={r['gap_max_ms']:7.2f}ms  "
              f"(load {r['load_rps']:.0f} rps)")

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f"\nWrote {len(rows)} rows to {args.out} in {elapsed:.1f}s")
    print("\n" + _headline(rows))


if __name__ == "__main__":
    main()
