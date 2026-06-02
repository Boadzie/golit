# Deploying Golit

Golit runs as a single process out of the box. This guide covers going wider:
multiple workers and hosts, with the SSE push channel intact.

## The one thing to understand: session state is worker-local

Each client gets a server-side **session** — its own kernel graph and its current
Polars values — kept in the worker's memory and keyed by the `golit_session`
cookie. That locality is deliberate: it's what makes recompute cost track the
*change*, not the program. Serializing DataFrames to a shared store on every
interaction would throw that away.

The consequence: **every request from one client must reach the worker that holds
its session** — the initial `GET /`, each `POST /node/...`, and the long-lived
`GET /events` SSE stream. That's *session affinity* ("sticky sessions").

The second consequence: a server-side invalidation (a streaming source, a
background job, a shared node) originates on one worker but must reach the worker
holding each *affected* client's SSE connection. That's what **Redis pub/sub**
provides — one `publish`, delivered to every worker.

So horizontal scale is two pieces, and you need both:

| Piece | Mechanism | Without it |
| --- | --- | --- |
| Stick a client to one worker | Load balancer, hashing the `golit_session` cookie | Returning client hits a worker with no session → re-rendered from defaults |
| Reach every worker on invalidation | `GOLIT_REDIS_URL` → `RedisPubSub` | SSE pushes only reach clients on the publishing worker |

## Single node (default)

```bash
golit run examples/sales_explorer/app.py
```

One process, in-memory fan-out (`InMemoryPubSub`). Nothing else to configure.

## Turning on Redis

Set one environment variable; `create_app` selects `RedisPubSub` automatically
(it's an optional dependency — install with the `redis` extra):

```bash
pip install "golit[redis]"
export GOLIT_REDIS_URL=redis://localhost:6379
golit run examples/sales_explorer/app.py
```

Programmatic override, if you'd rather not use the environment:

```python
from golit import create_app
from golit.server import RedisPubSub

application = create_app(app, pubsub=RedisPubSub("redis://redis:6379"))
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

- **Worker restart drops that worker's sessions.** Clients reconnect and
  re-render on the next `GET /` — there's no persistence of in-flight session
  state by design. Keep source `@app.source` functions cheap/idempotent.
- **Redis is for invalidation fan-out only**, not session storage. It carries
  small JSON messages (`node_id`, `session`); it never holds DataFrames.
- **Scaling Redis:** a single instance handles a large fan-out fine. Redis
  pub/sub is at-most-once and not persisted — acceptable here because an
  invalidation just asks a worker to recompute current state, which it can always
  redo on the next interaction.
- **Sizing:** memory is dominated by live session values (Polars frames × active
  sessions). Scale replicas on memory, and front them with the sticky balancer.
