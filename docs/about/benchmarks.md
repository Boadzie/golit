# Benchmarks

!!! info "Status: harness built, preliminary dev-laptop results — formal publication pending"
    Golit's performance thesis is the heart of the project, so the bar for *claiming* it is high. The benchmark harness and rival apps now exist — see [`bench/`](https://github.com/boadzie/golit/tree/main/bench) — and the numbers quoted on this page are **measured and reproducible** (`uv run --no-sync python -m bench.<name>`). They were taken on a **dev laptop over loopback**, which is enough to establish the *shape* of the result but not the final figures: the disclosure bar below (standard cloud instance, pinned versions, ≥5 runs) is what a headline launch number must clear, and that run is still pending. Read the numbers here as "the curve is real and reproducible," not "the official benchmark."

## Guiding principle

**Measure the thing the architecture actually changes.** Golit's claim is *update cost is proportional to the change, not the program*. So the benchmark isolates **incremental update latency** and **concurrent-user scaling** — not cold start, and not raw compute (that's just Polars vs Pandas, a separate story).

## Credibility rules

A performance claim that doesn't survive scrutiny is worse than none. The methodology forbids the usual ways to cheat:

- **No cherry-picked pathological scripts** (e.g. a Streamlit app that reloads a 1 GB CSV per rerun).
- **Caching enabled on the competition.** Streamlit runs with `@st.cache_data` and the `fragment` API where applicable. You must win *with* their cache on, or the win is fake.
- **Distributions, not a single number.** Report p50 / p95 / p99 over many runs.
- **Full disclosure.** Hardware, versions, and the complete app source are published.

## The comparison set

| Framework | Why it's in | Configuration |
| --- | --- | --- |
| **Streamlit** | The default you must beat | `@st.cache_data` on, `fragment` API where applicable |
| **Marimo** | Direct rival — also reactive | Default reactive mode |
| **Dash** | The production incumbent | Callbacks scoped to outputs |
| **Golit** | — | Kernel on, Redis backing on |

Including Marimo is non-negotiable: omitting the one framework that shares the thesis would (rightly) cost trust.

## The three benchmarks

### B1 — Incremental update latency (the core claim)

A fixed app: load a dataset once, then one slider feeds filter → aggregate → chart. Measure time from input change to updated UI on the wire, dataset already warm.

- **Vary** dataset size {10K, 100K, 1M, 10M rows} and graph depth {1, 3, 10 nodes}.
- **The decisive plot:** latency vs *number of unaffected nodes*. Golit should stay flat; full-rerun frameworks should climb. This single chart is the argument.
- **Metric:** server compute time *and* end-to-end (event → rendered fragment), p50/p95/p99.

### B2 — Concurrent-user scaling (the production claim)

The same app under load — ramp {1, 10, 50, 100, 500, 1000} users driving the slider on a realistic cadence.

- **Metric:** p99 latency and error rate vs concurrency; throughput at saturation.
- **The decisive result:** the concurrency at which p99 crosses an unusable threshold.
- **Honesty requirement:** report worker count and Redis config. Scaling that needs 10× the boxes isn't scaling.

### B-memo — Shared-upstream memoization (the production shape)

B1 is a single chain, where Golit and Dash do identical work and tie. Real dashboards share an expensive upstream across several views; this benchmark builds that shape — `data → heavy → {view_a, view_b}` — and moves a control that affects only one view.

- **The decisive contrast:** Golit re-runs only the affected view (the shared `heavy` is clean → memoized, executed **zero** times per update — asserted from the kernel's exec count); idiomatic Dash recomputes `heavy` inside the callback every interaction.
- **Both engines run the same Polars functions** and return the same raw-dict chart, so the comparison isolates *recompute-vs-memoize*, not the data engine or the chart object.
- **Measured** ([`run_memo`](https://github.com/boadzie/golit/tree/main/bench/run_memo.py) in-process, [`run_memo_http`](https://github.com/boadzie/golit/tree/main/bench/run_memo_http.py) end-to-end): the gap is ~the cost of the shared step and widens with it.

### B3 — Payload per update

Bytes on the wire per interaction (HTMX fragment + SVG vs JSON/WebSocket diff vs client-rendered), and whether a client JS framework must boot. Supporting evidence, not the headline.

## Harness

- **Driver:** [k6](https://k6.io/) or Locust, hitting each framework through its *real* transport.
- **Warmup:** discard the first 30s; measure steady state, not cold start.
- **Runs:** ≥ 5 independent runs per configuration; report mean ± stddev of the percentiles.
- **Isolation:** one framework per run, CPU-pinned, no other load on the box.
- **Disclosure:** exact hardware (re-run on a standard cloud instance, not just a dev laptop), pinned versions, full app source, load scripts, raw CSVs, and the analysis notebook — all public.

## Results so far (dev laptop, loopback — reproducible, not yet the published figures)

The honest summary of what the harness measures today. Per-update latency, p50, same chart on both sides; full source in [`bench/`](https://github.com/boadzie/golit/tree/main/bench).

- **Single chart, single chain (B1):** Golit ≈ Dash (~2 ms over HTTP). Identical work, no winner — and saying otherwise would be the kind of overstatement these rules exist to prevent.
- **Chart payload (B3):** returning a Plotly *figure* ties Dash; handing over a raw spec dict with [`chart_spec`](../tutorial/charts.md#the-hot-path-chart_spec) drops the update to ~1.5 ms and ~635 B (vs ~6.9 KB) — **~1.4× faster than figure-returning Dash with a ~10× smaller payload**, same chart.
- **Shared upstream (B-memo), over real HTTP:** Golit stays roughly flat as the shared step grows while Dash climbs with it — **~1.6× at 100K rows, ~5.5× at 1M, ~8.3× at 2M**. This is the result that tracks how real dashboards are built.
- **Concurrency (B2):** a single instance saturates around a few thousand req/s on the laptop; sticky-instance scaling is roughly linear to 4 instances. The update offload (keeping a heavy update off the event loop) is neutral on light updates and protects co-located sessions' SSE push cadence under heavy ones ([`run_b2_push`](https://github.com/boadzie/golit/tree/main/bench/run_b2_push.py)).

Each bullet has a one-command repro under `bench/`. None of it is the cloud-instance, multi-run, version-pinned publication the launch number requires — that's the next step, not a finished claim.

## Reporting

A credible report leads with two charts — B1's latency-vs-unaffected-nodes (flat Golit under a climbing rival) and B2's p99-vs-concurrency — backed by a percentile table and a **"threats to validity"** section that argues *against* the result (where Streamlit wins: cold start, tiny apps, ecosystem). Pre-empting objections earns more trust than any single number.

## The sentence this is designed to produce

The dev-laptop harness already produces the *shape* of it:

> On a dashboard whose 2M-row upstream feeds several views, changing one input updates the UI in ~1.8 ms on Golit vs ~15 ms on Dash over real HTTP — because Golit recomputes only the affected view and reuses the rest, while Dash repeats the shared work every callback.

What's left to turn that from "reproducible on a laptop" into "the launch number" is the disclosure bar above: a standard cloud instance, pinned versions, ≥5 runs, and the threats-to-validity section — not a different result, just a defensible one.
