# Golit

> **Streamlit, until it goes to production.**
>
> Golit is a reactive DAG framework for Python. It maps your data dependencies, then on every interaction recomputes only the nodes that changed — not your whole script. Rust core. Polars data. Server-rendered SVG charts. Scales horizontally on Redis.

**A high-performance Reactive Directed Acyclic Graph (DAG) framework for Python.**

Golit closes the gap between rapid data prototyping (Streamlit, Dash) and production-grade, horizontally scalable web applications. It keeps the single-file, write-Python-get-a-UI ergonomics of prototyping tools, but replaces their wasteful execution model with a precise reactive engine backed by a Rust compute kernel.

---

## The Problem

Conventional data frameworks re-execute the **entire script** on every interaction. Move a slider, and the framework re-loads the dataset, re-runs every transform, and re-renders every widget — even the ninety percent of the page that did not change. This is acceptable for a demo and untenable in production: latency scales with script size, not with the size of the change.

## The Core Vision: Blueprint Editorial

Golit treats your application as a **dependency graph, not a script**. At startup it compiles a DAG mapping every input, computation, and view to the nodes it depends on. When an input changes, Golit:

1. Marks the changed node **dirty**.
2. Propagates dirtiness downstream to only the transitively affected nodes.
3. Re-executes those nodes in topological order, reusing memoized results for everything else.
4. Re-renders **only** the UI fragments bound to recomputed nodes and surgically swaps them into the live DOM.

The result is sub-frame updates whose cost is proportional to the _change_, not the program.

---

## Architectural Tiers

Golit is a four-tier system. The lower the tier, the hotter the path and the closer to native code.

### Tier 0 — Compute Kernel (Rust + Polars)

The performance foundation. Two responsibilities, both compiled and FFI-light:

- **Reactive core**: dirty-tracking, topological scheduling, and propagation are implemented in Rust and exposed to Python via PyO3. The graph walk that runs on _every_ interaction never pays Python interpreter overhead.
- **Data engine**: all columnar work is delegated to **Polars** (itself Rust-native). DataFrames live as Arrow buffers and are passed between nodes **zero-copy** — only lightweight node handles cross the FFI boundary, never the data itself.

This means a filter-and-aggregate pipeline runs entirely in optimized Rust; Python is the orchestration language, not the execution bottleneck.

### Tier 1 — Reactive Orchestrator (Litestar)

The async server-side brain. Litestar owns session state, the per-session node registry, request routing, and the scheduling loop that hands dirty subgraphs to the Tier 0 kernel and streams results back out. Chosen over FastAPI for its first-class DI, lifecycle hooks, and lower per-request overhead under load.

**Why Litestar, not FastAPI?** FastAPI owns Python mindshare, so this choice draws questions. Litestar _is_ measurably faster — its msgspec serialization benchmarks ~10–20x faster than Pydantic v2, and real migrations report 40–120% throughput gains — but that edge lives in **serialization-heavy JSON workloads**, and Golit barely serializes: the wire format is pre-rendered HTML/SVG fragments, not validated JSON models. So the honest framing is: Litestar is faster on JSON-serialization workloads via msgspec; for Golit it's chosen for first-class **dependency injection** (clean per-session scoping of the node registry) and **lifecycle hooks** (the SSE connection and Redis subscription bind naturally to startup/shutdown), with lower base overhead — the speed edge is a bonus, not the reason. The reactive engine is also **framework-agnostic**: Litestar is the host, not the moat, so a FastAPI adapter remains a viable future path if community demand warrants it.

### Tier 2 — Transport Layer (HTMX + Lets-Plot)

Instead of shipping raw JSON for the client to reconcile, the server emits **pre-rendered HTML fragments**. HTMX swaps each fragment into its target element by ID. The wire format is the final UI — no client-side diffing framework, no hydration, minimal payload.

Charts use **[Lets-Plot](https://lets-plot.org/)**, a grammar-of-graphics library (a faithful Python port of R's ggplot2). It runs in **static, no-JavaScript mode** (`LetsPlot.setup_html(no_js=True)` / `plot.to_svg()`), emitting **bare-bones SVG** server-side. This is the decisive fit: a chart is rendered to SVG in Tier 1 and swapped in as just another HTML fragment — no client charting runtime, no per-chart JS bundle, and the visual is self-contained markup that an HTMX swap handles like any other. View nodes consume Polars frames directly and return `ggplot` specs; Golit compiles them to SVG only when the node is dirty.

**Bring your own charts.** Lets-Plot is the default, not a cage. Python developers overwhelmingly reach for Matplotlib, Plotly, or Altair, and a framework that supported only one library would feel restrictive. The real constraint is architectural, not brand: **any library that exports static SVG/PNG/HTML server-side** drops straight into the fragment model — Matplotlib (`savefig` to SVG), Plotly/Altair static export (via Kaleido / `vl-convert`), or a raw SVG string all work. The one path that breaks the pure-fragment story is a chart that requires a **client-side JS runtime** to render (interactive Plotly/Altair widgets); those need their bundle loaded and are supported only via the opt-in interactive escape hatch, not the default SVG-swap path. A view node returns any object Golit knows how to serialize to markup; Lets-Plot is simply the batteries-included choice.

#### Two channels: POST in, SSE out

Input and output travel on **separate channels**, matching the actual direction of data flow:

- **Input (client → server): plain HTMX `POST`.** A user interaction commits a value (slider release, input blur, button click) and fires an `hx-post`. The server runs the dirty subgraph and returns the affected fragments **in the same response**, swapped immediately. This covers the common case — a user changing their own inputs — with no persistent connection at all.
- **Updates (server → client): Server-Sent Events.** Some nodes go dirty for reasons the requesting client did not trigger: a streaming source advances, a background job finishes, a shared/global node is recomputed for everyone. These are **server-initiated** and **unidirectional**, which is exactly SSE's shape. Each session holds one long-lived `EventSource`; the server emits a named event per dirty fragment, and HTMX's SSE extension swaps it by name.

```html
<!-- Input: committed change → POST → fragments swapped in the response -->
<input
  type="range"
  name="threshold"
  hx-post="/node/threshold"
  hx-trigger="change"
  hx-target="#chart"
  hx-swap="outerHTML"
/>

<!-- Updates: one SSE stream per session; events named per node -->
<div hx-ext="sse" sse-connect="/events">
  <div id="chart" sse-swap="node:chart">…</div>
  <div id="kpi" sse-swap="node:kpi">…</div>
</div>
```

The event name _is_ the node identity: when node `chart` goes dirty from a server-side cause, Golit renders its fragment and emits `event: node:chart`, and HTMX swaps `#chart`. Same fragment-by-name contract as the POST path, just pushed.

#### Why SSE over WebSocket

- **Direction matches the model.** Input already has its own channel (POST); the push channel only ever flows server → client. WebSocket's bidirectionality would be paid for and unused.
- **Scales statelessly.** SSE rides plain HTTP, so any worker can serve any stream. WebSocket connections are stateful and pinned to a worker, which fights the "any worker serves any request" design and forces sticky sessions or a socket-aware broker.
- **Operationally cheap.** SSE auto-reconnects and passes through proxies and load balancers cleanly; WebSocket reconnect is hand-rolled and proxies are flakier.
- **Payload is text.** Fragments are HTML/SVG, so SSE's text-only limit costs nothing.

> **Deployment note:** SSE over HTTP/1.1 hits the browser's ~6-connections-per-host cap. Serve over **HTTP/2** in production (multiplexed streams) and the limit is a non-issue. WebSocket would only be reconsidered if Golit later adds genuinely bidirectional, low-latency features (collaborative cursors, multiplayer editing).

#### Redis → SSE fan-out

The push channel is how Golit propagates **shared invalidations** across a horizontally-scaled fleet. Workers are stateless; the SSE streams they hold are fed from Redis:

```
shared node dirties (any worker)
        │  PUBLISH invalidate {node, session_scope}
        ▼
   Redis pub/sub  ──fan-out──▶  every worker subscribed
        │
        ▼
each worker renders the fragment for its connected sessions
        │  event: node:chart  \n  data: <svg …>
        ▼
   open EventSource per client  ──▶  HTMX sse-swap by name
```

- A node invalidation is published once to Redis; every worker receives it and pushes the re-rendered fragment to whichever sessions it currently serves.
- **Scope** rides on the message: a _global_ node (e.g. a dataset reloaded for all users) fans out to every session; a _session-scoped_ node reaches only its owner's stream.
- Because the SSE connection is the only stateful thing and it carries no business state (just an open HTTP response), losing a worker drops the stream and the client's `EventSource` transparently reconnects to another worker.

### Tier 3 — Local Shield (Alpine.js)

Handles interactions that must feel instantaneous and never need the server: slider drag feedback, input debouncing, optimistic toggles, local form state. The Shield absorbs high-frequency events and only escalates to the server when a _committed_ value actually changes, protecting Tier 1 from chatter.

```
Browser  ──[Alpine.js: local immediacy]──┐
   ▲                                       │ committed change
   │ HTML fragment swap (HTMX)             ▼
Litestar Orchestrator ──schedule──▶ Rust Kernel (propagate) ──▶ Polars (compute)
                                                   │
                                          memoized node cache
```

---

---

## Scope Discipline

Golit lives or dies on one thing: whether `@app.source → @app.reactive → @app.view` delivers sub-50ms dirty-subgraph updates that stay flat as an app grows. **Until that is proven (benchmark B1), everything else is decoration** — the auth portal, deployment manager, component gallery, and observability screens are real eventual needs but premature investments today. The roadmap above is intentionally listed as _design_, not _built_. Build order follows the benchmark methodology: prove the core loop first, expand the surface second.

---

## Programming Model

Nodes are plain Python functions. Dependencies are inferred from parameters: a parameter named after another node _is_ an edge in the DAG.

```python
import polars as pl
from golit import App, slider, upload

app = App(title="Sales Explorer")

@app.source
def data(file=upload("Upload CSV")) -> pl.DataFrame:
    return pl.read_csv(file)

@app.reactive
def filtered(data: pl.DataFrame, threshold: int = slider(0, 100, default=20)) -> pl.DataFrame:
    # Re-runs only when `data` or `threshold` is dirty.
    return data.filter(pl.col("revenue") > threshold)

@app.view
def chart(filtered: pl.DataFrame):
    # Re-renders only when `filtered` changes.
    # A Lets-Plot grammar-of-graphics spec; Golit renders it to an SVG fragment.
    return (
        ggplot(filtered, aes("region", "revenue"))
        + geom_bar(stat="identity", fill="#1565C0")
        + ggsize(640, 360)
    )
```

Moving the slider dirties `threshold` → `filtered` → `chart`. The `data` node is never touched; its Polars frame stays resident in the Rust kernel. Only the `chart` fragment is swapped.

### Node Schema

| Field             | Type                          | Purpose                                               |
| ----------------- | ----------------------------- | ----------------------------------------------------- |
| `id`              | `str`                         | Stable identity, derived from function name + session |
| `kind`            | `source \| reactive \| view`  | Execution and render semantics                        |
| `deps`            | `list[NodeId]`                | Inbound edges, inferred from signature                |
| `hash`            | `u64`                         | Content hash of inputs; cache key for memoization     |
| `state`           | `clean \| dirty \| computing` | Drives the propagation pass                           |
| `fragment_target` | `str?`                        | DOM element ID (views only)                           |

---

## Planned Design Suite (Roadmap)

> These are **designs, not shipped features**. The project's value rests entirely on the core reactive loop (below); everything here is downstream of proving it.

A design suite visualizing the intended ecosystem, unified under the **Blueprint Editorial** design system (signature accent `#1565C0`, Material Blue 800 — engineering precision and reliability):

- **Marketing & Community** — high-impact Home page and a Contributing hub to drive open-source adoption.
- **Developer Experience** — API Reference, Getting Started guide, and a Component Gallery showcasing the reactive primitives.
- **Observability** — a DAG Graph Explorer for visualizing node propagation in real time, and an Error Boundary screen for system health.
- **Operations** — a Deployment & Scaling Manager for Redis-backed worker fleets, and an Auth Portal for secure access.

---

## Horizontal Scaling

Sessions are stateless at the HTTP edge; node state and memoization caches are backed by **Redis**, letting any worker serve any request. The Tier 0 kernel runs in-process per worker, so adding workers adds compute linearly. Redis also fans out invalidations for shared/global nodes (e.g. a dataset reloaded for all users).

---

## How Golit Compares

|                  | Streamlit          | Dash        | **Golit**                  |
| ---------------- | ------------------ | ----------- | -------------------------- |
| Execution unit   | Full script        | Callback    | **Dirty subgraph**         |
| Update cost      | ∝ script size      | ∝ callback  | **∝ change**               |
| Wire format      | WebSocket diff     | JSON        | **HTML fragments**         |
| Data engine      | Pandas             | Pandas      | **Polars (Rust)**          |
| Charting         | Plotly/Altair (JS) | Plotly (JS) | **Lets-Plot → static SVG** |
| Reactive core    | Python rerun       | Python      | **Rust (PyO3)**            |
| Horizontal scale | Hard               | Manual      | **Redis-backed, native**   |

> Use this for the component gallery: https://ui.shadcn.com/docs/js
