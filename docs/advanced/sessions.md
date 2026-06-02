# Sessions & state

Understanding where state lives is the key to deploying Golit. It's one idea, and everything about scaling follows from it.

## What a session is

Each client gets a server-side **session**, keyed by the `golit_session` cookie. A session holds two things:

- a **kernel graph** — this client's node states and memo hashes, and
- a **value registry** — this client's current node values (the Polars frames, scalars, and rendered fragments).

The `App` blueprint — the topology, the functions — is **shared** across all sessions. Only the *state* is per-session. So two users moving sliders independently each have their own filtered frames and their own clean/dirty bookkeeping, over one set of node definitions.

## State is worker-local — by design

A session lives in the **memory of the worker that created it**. It is *not* written to a shared store on each interaction. That locality is deliberate: it's exactly what makes recompute cost track the change. Serializing DataFrames to Redis or a database on every slider move would throw that away and reintroduce the cost Golit exists to avoid.

!!! abstract "The default rule"
    A client's requests are cheapest on the worker that already holds its session — the initial `GET /`, each `POST /node/…`, and the long-lived `GET /events` stream. That's *session affinity* ("sticky sessions"), the recommended default the [deployment story](deployment.md) is built around. With a Redis **session store** it stops being a *hard* rule: the input state is durable, so a request that lands elsewhere reconstructs the session rather than losing it.

## Lifecycle

| Event | What happens |
| --- | --- |
| First `GET /` with no/unknown cookie | A session is created, the cookie is set, and the graph is computed once (initial render). |
| `POST /node/{id}` | The input is coerced and stored; the dirty subgraph runs; changed fragments return. |
| `GET /events` | The session's SSE stream opens; server-pushed fragments flow to this client. |
| Worker restart | That worker's warm caches are gone. Clients re-render from defaults next `GET /` — or, with a Redis session store, reconstruct from their stored inputs. |

A session is always reconstructible — that's the point. Without a session store, a returning client whose session is missing just renders from defaults again. With one (`RedisSessionStore`, via `GOLIT_REDIS_URL`), the worker rebuilds the session from the client's stored inputs (replay + recompute), so state survives a worker restart, a rebalance, or a request that lands on a different replica. Only the inputs are persisted — never the frames.

!!! tip "Keep sources cheap and idempotent"
    Because a session can be rebuilt at any time (worker restart, new worker), your `@app.source` functions should be inexpensive and side-effect-free to call again. Treat the initial render as something that can happen more than once.

## Memory sizing

Memory is dominated by **live session values** — roughly the size of your Polars frames times the number of active sessions. When you size and scale workers, that's the figure to watch. Two practical levers: keep per-session frames lean (filter/aggregate early), and scale replicas on memory headroom.

## Where this leads

Two consequences define how Golit scales horizontally:

1. **Affinity.** Keep each client on one worker (the load balancer hashes the session cookie) — the recommended default; the Redis session store turns it into a warm-cache optimization rather than a correctness requirement.
2. **Fan-out.** A server-side invalidation must still reach whichever worker holds each affected client's SSE stream — that's [Redis pub/sub](server-push.md).

Both, and the exact topology, are in **[Deployment & scaling](deployment.md)**.
