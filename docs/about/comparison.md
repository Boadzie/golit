# Golit vs Streamlit & Dash

Golit lives in the same neighborhood as Streamlit and Dash — write Python, get a data UI — but it makes a different core bet about *how much work an interaction should cost*.

## At a glance

|                  | Streamlit          | Dash        | **Golit**                  |
| ---------------- | ------------------ | ----------- | -------------------------- |
| Execution unit   | Full script        | Callback    | **Dirty subgraph**         |
| Update cost      | ∝ script size      | ∝ callback  | **∝ change**               |
| Wire format      | WebSocket diff     | JSON        | **HTML fragments**         |
| Data engine      | Pandas             | Pandas      | **Polars (Rust)**          |
| Charting         | Plotly/Altair (JS) | Plotly (JS) | **Lets-Plot → static SVG** |
| Reactive core    | Python rerun       | Python      | **Rust (PyO3)**            |
| Horizontal scale | Hard               | Manual      | **Redis-backed, native**   |

## The execution model is the difference

**Streamlit** re-runs your *entire script* on every interaction. It's a wonderful model for getting something on screen fast, and `@st.cache_data` blunts the cost of expensive steps. But the default unit of work is the whole program, so as an app grows, an interaction does more work even when the *change* is tiny.

**Dash** is callback-based: you register callbacks mapping specific inputs to specific outputs. That's more surgical than a full rerun, but you wire the graph by hand, and the cost is the callback you wrote.

**Golit** infers the dependency graph from your function signatures and recomputes the **exact** set of downstream nodes a change affects — then memoizes within that set so unchanged values don't propagate. You don't wire callbacks, and you don't re-run the program. Cost tracks the change. ([How it works](../concepts/reactivity.md).)

## Where the difference actually shows up

Be honest about where it *doesn't*: on a **single** filter → aggregate → chart chain, Golit and Dash do the same work and finish in about the same time (~2 ms per update for the same chart on a dev laptop). One callback, one dirty subgraph — there's no slack to exploit.

The gap opens on the shape real dashboards actually have: **shared upstream work**. One expensive step — a load, a join, a sort — feeds several views. Move a control that affects only one view and the engines diverge:

- **Golit** re-runs only that view. The shared upstream is unchanged, so its memoized value is reused — it executes **zero** times.
- **Dash** re-runs the whole callback body, recomputing the shared upstream **every** interaction (it has no cross-callback memo; `dcc.Store` avoids the recompute only by serializing the intermediate to the browser and back — usually a worse trade).

In the [benchmark](benchmarks.md) (shared upstream feeding two views, move one slider, over real HTTP on a dev laptop), Golit's per-update latency stays roughly flat as the shared step grows while Dash's climbs with it — **~1.6× faster at 100K rows, ~5.5× at 1M, ~8.3× at 2M**. The win isn't a faster stopwatch on one chart; it's *not repeating work the change didn't touch*, and it widens as the app gets richer.

!!! note "The data engine is a separate axis"
    These numbers hold the data work constant (Polars on both sides) to isolate the *engine*. Against a typical Pandas-based Dash app, Golit's Polars compute is a further, independent advantage — but that's a Polars-vs-Pandas story, not a reactivity one.

## Where each shines

- **Reach for Streamlit** for a quick exploratory script, a notebook-style narrative, or a demo where the dataset is small and rerun cost is irrelevant. Its ecosystem and component breadth are large.
- **Reach for Dash** when you want explicit, fine-grained control over callbacks and you're already invested in its component model.
- **Reach for Golit** when interaction latency must stay flat as the app grows, when you want server-rendered fragments instead of a client framework, and when you need to scale horizontally without re-architecting.

## A note on fairness

The performance claim — *update cost is proportional to the change* — is only meaningful if it's measured honestly: caching enabled on the competition, distributions not single numbers, source and hardware published. That methodology is spelled out under [Benchmarks](benchmarks.md), including where Streamlit legitimately wins.

## What Golit is *not*

Golit isn't trying to be a general web framework (that's Litestar/FastAPI, and Golit is built *on* Litestar), nor a notebook, nor a BI tool. It's a focused answer to one question: how do you keep prototyping ergonomics while making interactions cost what the change costs — and ship that to production.
