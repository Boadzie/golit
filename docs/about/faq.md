# FAQ

### Do I need to know Rust to use Golit?

No. The Rust kernel ships precompiled in the wheel. You only need a Rust toolchain to build Golit *from source* — see [Contributing](contributing.md).

### Is this just Streamlit with extra steps?

No — the execution model is fundamentally different. Streamlit re-runs your whole script per interaction; Golit recomputes only the dirty subgraph and memoizes within it. The API *feels* similarly simple, but the cost model is "proportional to the change". See [the comparison](comparison.md).

### How are dependencies between nodes declared?

You don't declare them — they're **inferred from function parameters**. A parameter named after another node is an edge; a parameter defaulting to a widget is an input. See [The reactive graph](../tutorial/the-graph.md).

### Can a view return a pandas DataFrame / Matplotlib figure / my own object?

Yes. Golit's renderer handles Polars frames, pandas (`_repr_html_`), Matplotlib (`savefig`), anything with `to_svg()`, and your own types via the [`__golit_render__` protocol](../advanced/custom-rendering.md). Full [resolution order here](../tutorial/views.md#what-a-view-can-return).

### Do I have to use Lets-Plot for charts?

No. Lets-Plot (static SVG) is the batteries-included default, but you can return Plotly/Altair/Bokeh figures (auto-detected, interactive), use `anychart`, or return any object that exports SVG/PNG/HTML. See [Charts](../tutorial/charts.md).

### Is there a client-side JavaScript framework?

No React, no client diffing framework. The wire format is pre-rendered HTML/SVG fragments swapped by [HTMX](https://htmx.org/). A small [Alpine.js](https://alpinejs.dev/) "local shield" handles instantaneous UI feel (slider drag, tabs); interactive charts lazy-load their own CDN runtime only when present.

### How do I push an update without a user interaction?

Publish an `Invalidation` to the pub/sub channel; it's recomputed and pushed over SSE. Streaming sources, background jobs, and shared nodes use this. See [Server-push updates](../advanced/server-push.md).

### Does Golit support WebSockets? Can I build a chat?

Yes. SSE handles reactive push (server→client); for *bidirectional* features Golit has a WebSocket channel and a `ui.chat` component — room broadcast by default, plus an `@app.on_message` hook for bots/assistants/moderation. It still speaks server-rendered fragments (HTMX `ws` extension), no client framework. See [WebSocket chat](../advanced/websockets.md).

### Why Litestar instead of FastAPI?

For first-class dependency injection (per-session registry scoping) and lifecycle hooks (SSE + Redis bind to startup/shutdown), with low base overhead. The reactive engine is framework-agnostic — Litestar is the host, not the moat. [More here](../concepts/architecture.md#tier-1-orchestrator-litestar).

### Can I run multiple workers?

Yes, but not with `uvicorn --workers` — session state is worker-local, and that flag gives no session affinity. The production topology is N single-worker instances behind a sticky (cookie-hash) load balancer + Redis for fan-out. See [Deployment & scaling](../advanced/deployment.md).

### Does session state persist across restarts?

No, by design. A worker restart drops its sessions; clients re-render from defaults on the next request. Keep `@app.source` functions cheap and idempotent. See [Sessions & state](../advanced/sessions.md).

### What Python versions are supported?

Python **3.11+**.

### What's the license?

[Apache-2.0](https://github.com/boadzie/golit/blob/main/LICENSE).
