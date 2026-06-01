# Golit Benchmark Methodology: Technical Specification

## Guiding Principle
Measure the thing the architecture actually changes. Update cost is proportional to the change, not the program. Isolate incremental update latency and concurrent-user scaling.

## The Three Benchmarks

### B1: Incremental Update Latency
- **Goal:** Prove "cost ∝ change".
- **Setup:** Fixed app, dataset loaded once, one input slider feeds a filter -> aggregate -> chart.
- **Variables:** Dataset size {10K to 10M rows}, Graph depth {1 to 10 nodes}.
- **Decisive Plot:** Latency vs. Number of Unaffected Nodes (Golit stays flat, others climb).

### B2: Concurrent-User Scaling
- **Goal:** Production-grade performance proof.
- **Setup:** Same app under load (1 to 1000 concurrent users).
- **Decisive Plot:** p99 latency crossing threshold (500ms).

### B3: Payload / Bandwidth per Update
- **Goal:** Supporting evidence for HTMX-fragment + SVG story.
- **Metric:** Bytes on the wire per interaction.

## Comparison Set
- **Streamlit:** Default with `@st.cache_data` and fragments.
- **Marimo:** Non-negotiable reactive rival.
- **Dash:** Production incumbent with scoped callbacks.
- **Golit:** Tier 0 kernel, Redis-backed.

## Reproducibility
- AWS c7i.2xlarge standard cloud instance.
- Pinned versions, public repo with all source code and load scripts.
- Distributions (p50/p95/p99) reported over ≥ 5 independent runs.