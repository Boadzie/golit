# Architecture — the four tiers

Golit is a four-tier system. The lower the tier, the hotter the path and the closer to native code.

| Tier | Role | Tech |
| --- | --- | --- |
| **0** | Reactive kernel | Rust + PyO3 (`src/`, `golit._golit`) |
| **1** | Orchestrator | Litestar + SSE / Redis fan-out (`golit.server`) |
| **2** | Transport | HTMX fragments; static SVG + interactive charts (`golit.rendering`) |
| **3** | Local shield | Alpine.js (widget immediacy, tab state) |

## Tier 0 — Reactive kernel (Rust + Polars)

The performance foundation, with two responsibilities:

- **Reactive core.** Dirty tracking, topological scheduling, and propagation are implemented in Rust and exposed to Python via PyO3. The graph walk that runs on *every* interaction never pays Python interpreter overhead. (The algorithm is [The reactive model](reactivity.md).)
- **Data engine.** All columnar work is delegated to **Polars** (itself Rust-native). DataFrames live as Arrow buffers and pass between nodes **zero-copy** — only lightweight node handles cross the FFI boundary, never the data.

A filter-and-aggregate pipeline therefore runs entirely in optimized Rust. Python is the orchestration language, not the execution bottleneck.

## Tier 1 — Orchestrator (Litestar)

The async server-side brain. [Litestar](https://litestar.dev/) owns session state, the per-session node registry, request routing, and the scheduling loop that hands dirty subgraphs to the Tier 0 kernel and streams results back.

??? question "Why Litestar, not FastAPI?"
    Litestar is chosen for first-class **dependency injection** (clean per-session scoping of the node registry) and **lifecycle hooks** (the SSE connection and Redis subscription bind naturally to startup/shutdown), with lower base overhead. Litestar's headline speed edge comes from msgspec serialization on JSON-heavy workloads — but Golit barely serializes (the wire format is pre-rendered HTML/SVG), so for Golit that speed is a bonus, not the reason. The reactive engine is **framework-agnostic**: Litestar is the host, not the moat, and a FastAPI adapter remains a viable future path.

## Tier 2 — Transport (HTMX + Lets-Plot)

Instead of shipping raw JSON for the client to reconcile, the server emits **pre-rendered HTML fragments**. [HTMX](https://htmx.org/) swaps each fragment into its target element by id. The wire format *is* the final UI — no client-side diffing framework, no hydration, minimal payload.

Charts default to **[Lets-Plot](https://lets-plot.org/)** in static, no-JavaScript mode, emitting **bare SVG server-side**. A chart is rendered to SVG in Tier 1 and swapped in as just another HTML fragment — no client charting runtime. Interactive Plotly/Altair/Bokeh figures are supported via an opt-in mount that hydrates client-side (see [Charts](../tutorial/charts.md)).

### Two channels: POST in, SSE out

Input and output travel on **separate channels**, matching the actual direction of data flow:

- **Input (client → server): plain HTMX `POST`.** A committed interaction fires an `hx-post`; the server runs the dirty subgraph and returns the affected fragments **in the same response**. No persistent connection needed for the common case.
- **Updates (server → client): Server-Sent Events.** Some nodes go dirty for reasons the requesting client didn't trigger — a streaming source advances, a background job finishes, a shared node recomputes for everyone. These are server-initiated and unidirectional, exactly SSE's shape.

The full trace is in [How a change flows](data-flow.md).

??? question "Why SSE over WebSocket?"
    The push channel only ever flows server → client (input has its own POST channel), so WebSocket's bidirectionality would be paid for and unused. SSE rides plain HTTP, so any worker can serve any stream; it auto-reconnects and passes through proxies cleanly; and fragments are text, so SSE's text-only limit costs nothing. (Serve over HTTP/2 in production to dodge the browser's ~6-connections-per-host cap on HTTP/1.1.)

    The exception is *genuinely bidirectional* features — Golit uses a real WebSocket for [chat](../advanced/websockets.md), the case this trade-off explicitly reserves it for. SSE remains the channel for reactive invalidations.

## Tier 3 — Local shield (Alpine.js)

[Alpine.js](https://alpinejs.dev/) handles interactions that must feel instantaneous and never need the server: slider-drag feedback, input debouncing, tab state. The shield absorbs high-frequency events and only escalates to the server when a **committed** value actually changes — protecting Tier 1 from chatter.

```
Browser  ──[Alpine.js: local immediacy]──┐
   ▲                                       │ committed change
   │ HTML fragment swap (HTMX)             ▼
Litestar Orchestrator ──schedule──▶ Rust Kernel (propagate) ──▶ Polars (compute)
                                                   │
                                          memoized node cache
```

## How the tiers collaborate

A slider drag lives entirely in Tier 3 until you let go. The release commits a value (Tier 2 POST) to the orchestrator (Tier 1), which asks the kernel (Tier 0) for the dirty subgraph, executes the Polars work (Tier 0), renders the changed views to fragments (Tier 2), and swaps them back. Each tier does the one thing it's best at, and the data never leaves the tier that owns it.

## See also

- [The reactive model](reactivity.md) — Tier 0 in depth.
- [Sessions & state](../advanced/sessions.md) and [Deployment & scaling](../advanced/deployment.md) — how Tier 1 scales out.
