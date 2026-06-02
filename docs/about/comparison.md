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

## Where each shines

- **Reach for Streamlit** for a quick exploratory script, a notebook-style narrative, or a demo where the dataset is small and rerun cost is irrelevant. Its ecosystem and component breadth are large.
- **Reach for Dash** when you want explicit, fine-grained control over callbacks and you're already invested in its component model.
- **Reach for Golit** when interaction latency must stay flat as the app grows, when you want server-rendered fragments instead of a client framework, and when you need to scale horizontally without re-architecting.

## A note on fairness

The performance claim — *update cost is proportional to the change* — is only meaningful if it's measured honestly: caching enabled on the competition, distributions not single numbers, source and hardware published. That methodology is spelled out under [Benchmarks](benchmarks.md), including where Streamlit legitimately wins.

## What Golit is *not*

Golit isn't trying to be a general web framework (that's Litestar/FastAPI, and Golit is built *on* Litestar), nor a notebook, nor a BI tool. It's a focused answer to one question: how do you keep prototyping ergonomics while making interactions cost what the change costs — and ship that to production.
