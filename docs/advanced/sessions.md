# Sessions & state

Understanding where state lives is the key to deploying Golit. It's one idea, and everything about scaling follows from it.

## What a session is

Each client gets a server-side **session**, keyed by the `golit_session` cookie. A session holds two things:

- a **kernel graph** — this client's node states and memo hashes, and
- a **value registry** — this client's current node values (the Polars frames, scalars, and rendered fragments).

The `App` blueprint — the topology, the functions — is **shared** across all sessions. Only the *state* is per-session. So two users moving sliders independently each have their own filtered frames and their own clean/dirty bookkeeping, over one set of node definitions.

## State is worker-local — by design

A session lives in the **memory of the worker that created it**. It is *not* written to a shared store on each interaction. That locality is deliberate: it's exactly what makes recompute cost track the change. Serializing DataFrames to Redis or a database on every slider move would throw that away and reintroduce the cost Golit exists to avoid.

!!! abstract "The one rule"
    **Every request from one client must reach the worker that holds its session** — the initial `GET /`, each `POST /node/…`, and the long-lived `GET /events` stream. That's *session affinity* ("sticky sessions"), and it's the constraint the whole [deployment story](deployment.md) is built around.

## Lifecycle

| Event | What happens |
| --- | --- |
| First `GET /` with no/unknown cookie | A session is created, the cookie is set, and the graph is computed once (initial render). |
| `POST /node/{id}` | The input is coerced and stored; the dirty subgraph runs; changed fragments return. |
| `GET /events` | The session's SSE stream opens; server-pushed fragments flow to this client. |
| Worker restart | That worker's sessions are gone. Clients re-render on their next `GET /`. |

There's no persistence of in-flight session state, and that's fine: a session is reconstructible. A returning client whose session is missing just renders from defaults again.

!!! tip "Keep sources cheap and idempotent"
    Because a session can be rebuilt at any time (worker restart, new worker), your `@app.source` functions should be inexpensive and side-effect-free to call again. Treat the initial render as something that can happen more than once.

## Memory sizing

Memory is dominated by **live session values** — roughly the size of your Polars frames times the number of active sessions. When you size and scale workers, that's the figure to watch. Two practical levers: keep per-session frames lean (filter/aggregate early), and scale replicas on memory headroom.

## Where this leads

Two consequences define how Golit scales horizontally:

1. **Affinity.** Stick each client to one worker (the load balancer hashes the session cookie).
2. **Fan-out.** A server-side invalidation must still reach whichever worker holds each affected client's SSE stream — that's [Redis pub/sub](server-push.md).

Both, and the exact topology, are in **[Deployment & scaling](deployment.md)**.
