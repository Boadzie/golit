# Golit Benchmark Methodology

The performance claim is the entire pitch for a US audience. A skeptical Python dev will dismiss "10x faster" unless the methodology is reproducible, the comparison is fair, and the numbers survive scrutiny on Hacker News. This document defines a benchmark you can publish, that others can re-run, and that you would not be embarrassed to defend in a thread.

## Guiding principle

**Measure the thing your architecture actually changes.** Golit's claim is _update cost is proportional to the change, not the program_. So the benchmark must isolate **incremental update latency** and **concurrent-user scaling** — not cold start, not raw compute (that's just Polars vs Pandas, a separate story). If you benchmark the wrong axis you'll win a fight nobody cares about.

## What you are NOT allowed to do (credibility killers)

- Cherry-pick a pathological Streamlit script (e.g. one that reloads a 1GB CSV on every rerun) — critics will call it rigged.
- Compare Golit-with-caching against Streamlit-without-`@st.cache_data` — Streamlit's cache is the obvious counter. You must enable it and still win, or your win is fake.
- Report a single number. Report distributions (p50/p95/p99) over many runs.
- Hide the hardware, versions, or the app source. Everything is published.

## The comparison set

| Framework     | Why it's in                                        | Configuration                                                  |
| ------------- | -------------------------------------------------- | -------------------------------------------------------------- |
| **Streamlit** | The default; the one you must beat                 | `@st.cache_data` enabled, `fragment` API used where applicable |
| **Marimo**    | Direct rival — also reactive, also "no full rerun" | Default reactive mode                                          |
| **Dash**      | The production incumbent                           | Callbacks scoped to outputs                                    |
| **Golit**     | You                                                | Tier 0 kernel on, Redis backing on                             |

Including Marimo is non-negotiable. If you omit the one framework that shares your thesis, every informed reader notices and trust collapses.

## The three benchmarks

### B1 — Incremental update latency (the core claim)

A fixed app: load a dataset once, then one input (slider) feeds a filter → aggregate → chart. Measure **time from input change to updated UI on the wire**, with the dataset already loaded and warm.

- **Vary**: dataset size {10K, 100K, 1M, 10M rows} and downstream graph depth {1, 3, 10 nodes}.
- **The decisive plot**: latency vs _number of unaffected nodes_. Golit should stay flat; full-rerun frameworks should climb. **This single chart is the argument** — it visually proves "cost ∝ change."
- **Metric**: server-side compute time AND end-to-end (input event → rendered fragment), p50/p95/p99.

### B2 — Concurrent-user scaling (the production claim)

The same app under load. Ramp concurrent users {1, 10, 50, 100, 500, 1000} driving the slider on a realistic cadence (e.g. one change every 2–5s with jitter).

- **Metric**: p99 update latency and error rate vs concurrency. Throughput (updates/sec) at saturation.
- **The decisive result**: the concurrency at which p99 crosses an unusable threshold (say 500ms) or errors appear. "Streamlit degrades at ~N users; Golit holds to ~M" is the production sentence that sells the enterprise tier.
- **Honesty requirement**: report Golit's worker count and Redis config. Scaling that needs 10x the boxes isn't scaling.

### B3 — Payload / bandwidth per update

Bytes on the wire per interaction (the HTMX-fragment + SVG story vs JSON/WebSocket diff vs client-rendered).

- **Metric**: transferred bytes per update, and whether a client JS framework must boot.
- **Why it matters**: ties to cost-at-scale and to the "no client charting runtime" claim. Smaller, defensible win — include it as supporting evidence, not the headline.

## Test harness

```
load generator (k6 or Locust)  ──HTTP──▶  app under test (1 process, pinned)
        │                                         │
   records: latency percentiles,            instrumented: server compute time
   throughput, error rate, bytes            (per-node timing where possible)
```

- **Driver**: [k6](https://k6.io/) or Locust. Same script hits every framework via its real transport (HTMX swap, WebSocket, callback POST) so you measure each as it actually ships.
- **Warmup**: discard the first 30s; caches and JITs must be hot. You're measuring steady-state interaction, not cold start.
- **Runs**: ≥ 5 independent runs per configuration; report mean ± stddev of the percentiles, not one run.
- **Isolation**: one framework per run, CPU-pinned, no other load on the box.

## Environment disclosure (publish verbatim)

- Exact hardware (cloud instance type + vCPU/RAM, or your M4 Pro spec) — **note**: dev-laptop numbers are suggestive; for the credible US-facing claim, re-run on a standard cloud instance (e.g. AWS `c7i.2xlarge`) so anyone can reproduce on identical metal.
- Pinned versions of every framework, Python, Polars, Redis, the OS.
- The **full source** of every app under test, in a public repo, one app per framework, behaviorally identical.
- The load scripts and the raw result CSVs.
- The analysis notebook that turns CSVs into the charts.

## Reporting format

1. **One hero chart** — B1's latency-vs-unaffected-nodes. Flat Golit line under a climbing Streamlit/Marimo line. This is what gets screenshotted and shared.
2. **One scaling chart** — B2's p99 vs concurrency. The production proof.
3. A results table with percentiles for every configuration.
4. A "Threats to validity" section where you argue _against yourself_. Listing where Streamlit wins (cold start? tiny apps? ecosystem?) and where your benchmark could be unfair earns more trust than any win. Skeptics who see you pre-empt their objection stop attacking and start believing.

## The sentence this produces

If the data holds, you walk away with something like:
_"On a 1M-row app with 10 downstream nodes, changing one input updates the UI in 18ms p99 on Golit vs 340ms on Streamlit with caching — and Golit holds sub-50ms p99 to 500 concurrent users where Streamlit crosses 1s at ~80."_

That sentence — with a reproducible repo behind it — is the launch. Without it, the vision doc is just prose.

## Build order

1. Write the four behaviorally-identical apps first. Getting them _truly_ equivalent is the hard, credibility-critical part.
2. Stand up the k6 harness against one framework end-to-end.
3. Run B1 (the core claim) and look at the hero chart before investing in B2/B3. If B1 doesn't show a clear flat-vs-climbing separation, stop and rethink the claim before publishing anything.
