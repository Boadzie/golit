# Benchmarks

!!! info "Status: methodology defined, results not yet published"
    Golit's performance thesis is the heart of the project, so the bar for *claiming* it is high. This page documents the benchmark methodology Golit holds itself to. The benchmark harness and rival apps are **not yet built**, so there are **no published numbers here yet** — when they exist, they'll appear with a reproducible repo behind them. The sample sentence at the bottom is illustrative of the *shape* of a result, not a measured figure.

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

### B3 — Payload per update

Bytes on the wire per interaction (HTMX fragment + SVG vs JSON/WebSocket diff vs client-rendered), and whether a client JS framework must boot. Supporting evidence, not the headline.

## Harness

- **Driver:** [k6](https://k6.io/) or Locust, hitting each framework through its *real* transport.
- **Warmup:** discard the first 30s; measure steady state, not cold start.
- **Runs:** ≥ 5 independent runs per configuration; report mean ± stddev of the percentiles.
- **Isolation:** one framework per run, CPU-pinned, no other load on the box.
- **Disclosure:** exact hardware (re-run on a standard cloud instance, not just a dev laptop), pinned versions, full app source, load scripts, raw CSVs, and the analysis notebook — all public.

## Reporting

A credible report leads with two charts — B1's latency-vs-unaffected-nodes (flat Golit under a climbing rival) and B2's p99-vs-concurrency — backed by a percentile table and a **"threats to validity"** section that argues *against* the result (where Streamlit wins: cold start, tiny apps, ecosystem). Pre-empting objections earns more trust than any single number.

## The sentence this is designed to produce

> *(illustrative shape, not a measured result)* — "On a 1M-row app with 10 downstream nodes, changing one input updates the UI in ~Xms p99 on Golit vs ~Yms on Streamlit with caching — and Golit holds sub-50ms p99 to N concurrent users."

That sentence, with a reproducible repo behind it, is the launch. Until the data is in, it stays explicitly hypothetical.
