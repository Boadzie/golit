# Deploying Golit

Golit runs as a single process out of the box. This guide covers going wider:
multiple workers and hosts, with the SSE push channel intact.

## The one thing to understand: session state is worker-local

Each client gets a server-side **session** — its own kernel graph and its current
Polars values — kept in the worker's memory and keyed by the `golit_session`
cookie. That locality is deliberate: it's what makes recompute cost track the
*change*, not the program. Serializing DataFrames to a shared store on every
interaction would throw that away.

The consequence: a client's requests are cheapest when they reach the worker that
already holds its session — the initial `GET /`, each `POST /node/...`, and the
long-lived `GET /events` SSE stream. That's *session affinity* ("sticky sessions").
It is the recommended default, but with Redis turned on it is no longer load-bearing
for correctness: the **session store** persists each session's *input* state, so a
request that lands on a worker without the live session **reconstructs** it from
those inputs (replay + local recompute) instead of starting from defaults. Affinity
then just keeps the in-memory session warm and avoids the same session diverging
across two workers under round-robin.

The second consequence: a server-side invalidation (a streaming source, a
background job, a shared node) originates on one worker but must reach the worker
holding each *affected* client's SSE connection. That's what **Redis pub/sub**
provides — one `publish`, delivered to every worker.

So horizontal scale is two pieces:

| Piece | Mechanism | Without it |
| --- | --- | --- |
| Keep a client on one worker (recommended) | Load balancer, hashing the `golit_session` cookie | A re-routed client reconstructs from Redis-stored inputs (a cold recompute) — or, with no session store, re-renders from defaults |
| Reach every worker on invalidation | `GOLIT_REDIS_URL` → `RedisPubSub` | SSE pushes only reach clients on the publishing worker |

## Single node (default)

```bash
golit run examples/sales_explorer/app.py
```

One process, in-memory fan-out (`InMemoryPubSub`). Nothing else to configure.

## Turning on Redis

Set one environment variable; `create_app` selects **both** Redis backends
automatically — `RedisPubSub` for invalidation fan-out and `RedisSessionStore` for
durable input state (Redis is an optional dependency — install with the `redis`
extra):

```bash
pip install "golit[redis]"
export GOLIT_REDIS_URL=redis://localhost:6379
golit run examples/sales_explorer/app.py
```

Programmatic override, if you'd rather not use the environment:

```python
from golit import create_app
from golit.server import RedisPubSub, RedisSessionStore

application = create_app(
    app,
    pubsub=RedisPubSub("redis://redis:6379"),
    session_store=RedisSessionStore("redis://redis:6379"),
)
```

## Horizontal scale: N instances behind a sticky load balancer

The supported HA topology is **N single-worker instances**, each on its own
port/container, behind a load balancer that pins clients by the session cookie,
all sharing one Redis.

> **Why not `uvicorn --workers N`?** uvicorn's workers share one socket with no
> affinity — the kernel hands each connection to whichever worker is free, so a
> client's `GET` and its `/events` stream can land on different workers, and
> neither holds the other's session. `golit run --workers N` exists for
> convenience and local testing and prints a warning; it is **not** the
> production path because it can't provide affinity.

### nginx

Open-source nginx can hash on a cookie, which gives consistent per-session
routing:

```nginx
upstream golit {
    hash $cookie_golit_session consistent;   # sticky by Golit's session cookie
    server app1:8000;
    server app2:8000;
    server app3:8000;
}
```

The SSE stream also needs buffering off and a long read timeout. The full config
is in [`deploy/nginx.conf`](deploy/nginx.conf).

## Run the whole stack locally (podman or docker)

[`deploy/`](deploy/) has a complete example: Redis + three single-worker replicas
+ the nginx sticky balancer.

```bash
# from the repo root
podman compose -f deploy/docker-compose.yml up --build
# open http://localhost:8000
```

- [`deploy/Dockerfile`](deploy/Dockerfile) — two-stage build: compile the Rust
  kernel to an abi3 wheel, then install it (with the `redis` extra) into a slim
  runtime.
- [`deploy/docker-compose.yml`](deploy/docker-compose.yml) — `redis`, `app1/2/3`
  (each `GOLIT_REDIS_URL=redis://redis:6379`), and `nginx` on port 8000.
- [`deploy/nginx.conf`](deploy/nginx.conf) — the cookie-hash upstream.

To prove affinity + fan-out: open the app, move the slider (the chart/KPI/table
swap — that's the local worker), then have a background source publish an
invalidation and watch it arrive over `/events` on the *other* replicas' clients.

## Operational notes

- **Worker restart loses that worker's warm caches, not the session.** Without a
  session store, clients re-render from defaults on the next `GET /`. With
  `RedisSessionStore` the input state is durable, so the session reconstructs (from
  inputs + a local recompute) on the next request to *any* worker. Either way, keep
  `@app.source` functions cheap/idempotent — the initial render can run again.
- **Redis never holds DataFrames.** Pub/sub carries small JSON (`node_id`,
  `session`); the session store holds only each session's *input* map
  (`{input_id: value}`). The derived frames stay worker-local — that's the thesis.
- **Scaling Redis:** a single instance handles a large fan-out fine. Redis
  pub/sub is at-most-once and not persisted — acceptable here because an
  invalidation just asks a worker to recompute current state, which it can always
  redo on the next interaction.
- **Sizing:** memory is dominated by live session values (Polars frames × active
  sessions). Scale replicas on memory, and front them with the sticky balancer.
