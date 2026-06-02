# Deployment & scaling

Golit runs as a single process out of the box. This page covers going wider — multiple workers and hosts — with the SSE push channel intact.

It all follows from one fact established in [Sessions & state](sessions.md): **session state is worker-local**. So horizontal scale is two pieces.

| Piece | Mechanism | Without it |
| --- | --- | --- |
| Keep a client on one worker (recommended) | Load balancer hashing the `golit_session` cookie | A re-routed client reconstructs from Redis-stored inputs (a cold recompute) — or, with no session store, re-renders from defaults |
| Reach every worker on invalidation | `GOLIT_REDIS_URL` → `RedisPubSub` | SSE pushes only reach clients on the publishing worker |

## Single node (the default)

```bash
golit run examples/sales_explorer/app.py
```

One process, in-memory fan-out (`InMemoryPubSub`). Nothing else to configure. This is the right setup for development and for plenty of production apps.

## Turning on Redis

Set one environment variable; `create_app` selects **both** Redis backends automatically — `RedisPubSub` for invalidation fan-out and `RedisSessionStore` for durable input state (it's an optional dependency — install with the `redis` extra):

```bash
pip install "golit[redis]"
export GOLIT_REDIS_URL=redis://localhost:6379
golit run examples/sales_explorer/app.py
```

Prefer to be explicit in code? Pass them directly:

```python
from golit import create_app
from golit.server import RedisPubSub, RedisSessionStore

application = create_app(
    app,
    pubsub=RedisPubSub("redis://redis:6379"),
    session_store=RedisSessionStore("redis://redis:6379"),
)
```

Redis never holds **DataFrames**: pub/sub carries small JSON, and the session store holds only each session's *input* map (`{input_id: value}`). The derived frames stay worker-local.

## Horizontal scale: N instances behind a sticky load balancer

The supported HA topology is **N single-worker instances**, each on its own port/container, behind a load balancer that pins clients by the session cookie, all sharing one Redis.

!!! warning "Why not `uvicorn --workers N`?"
    Uvicorn's workers share one socket with **no affinity** — the kernel hands each connection to whichever worker is free, so a client's `GET` and its `/events` stream can land on different workers, and neither holds the other's session. `golit run --workers N` exists for convenience and local testing (and prints a warning); it is **not** the production path, because it can't provide affinity.

### nginx

Open-source nginx can hash on a cookie, giving consistent per-session routing:

```nginx
upstream golit {
    hash $cookie_golit_session consistent;   # sticky by Golit's session cookie
    server app1:8000;
    server app2:8000;
    server app3:8000;
}
```

The SSE stream also needs buffering off and a long read timeout. A complete config ships in [`deploy/nginx.conf`](https://github.com/boadzie/golit/blob/main/deploy/nginx.conf).

## Run the whole stack locally

The [`deploy/`](https://github.com/boadzie/golit/tree/main/deploy) directory has a complete example — Redis + three single-worker replicas + the nginx sticky balancer:

```bash
# from the repo root (podman or docker)
podman compose -f deploy/docker-compose.yml up --build
# open http://localhost:8000
```

- **`deploy/Dockerfile`** — a two-stage build: compile the Rust kernel to an abi3 wheel, then install it (with the `redis` extra) into a slim runtime.
- **`deploy/docker-compose.yml`** — `redis`, `app1/2/3` (each `GOLIT_REDIS_URL=redis://redis:6379`), and `nginx` on port 8000.
- **`deploy/nginx.conf`** — the cookie-hash upstream.

To *prove* affinity + fan-out: open the app, move the slider (the chart/KPI/table swap — that's your local worker), then have a background source publish an invalidation and watch it arrive over `/events` on the *other* replicas' clients.

## Serve over HTTP/2

SSE over HTTP/1.1 hits the browser's ~6-connections-per-host cap. In production, terminate **HTTP/2** at the balancer (multiplexed streams) and the limit is a non-issue.

## Operational notes

- **Worker restart loses that worker's warm caches, not the session.** Without a session store, clients re-render from defaults on the next `GET /`. With `RedisSessionStore`, the input state is durable and the session reconstructs (inputs + a local recompute) on the next request to *any* worker. Keep `@app.source` functions cheap and idempotent — the initial render can run again.
- **Redis never holds DataFrames.** Pub/sub carries small JSON (`node_id`, `session`); the session store holds only each session's input map. Derived frames stay worker-local.
- **Scaling Redis:** a single instance handles a large fan-out fine. Pub/sub is at-most-once and not persisted — acceptable here, because an invalidation just asks a worker to recompute current state, which it can always redo on the next interaction.
- **Sizing:** memory is dominated by live session values (Polars frames × active sessions). Scale replicas on memory, fronted by the sticky balancer.

## See also

- [Sessions & state](sessions.md) — why locality is the design, not a limitation.
- [Server-push updates](server-push.md) — the invalidation channel that Redis fans out.
