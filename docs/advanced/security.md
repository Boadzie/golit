# Security & hardening

Golit's defaults are safe for development and many internal deployments. This page covers what to know — and the few switches to flip — before exposing an app to untrusted users on the public internet.

## Rendering: strings are trusted markup

A view that returns a `str` is emitted **verbatim**, as developer-authored markup — the same model as returning an `HTMLResponse` from a web framework:

```python
@app.view
def greeting(name: str = text("Name")) -> str:
    return f"<p>Hello {name}</p>"   # ⚠️ name is interpolated raw
```

That's deliberate — it's what lets you hand-write HTML — but it means any **untrusted** data you splice into a returned string (user input, a session value, an external API field) is an XSS sink. Escape it with `golit.escape`:

```python
import golit

@app.view
def greeting(name: str = text("Name")) -> str:
    return f"<p>Hello {golit.escape(name)}</p>"
```

Data that Golit renders **for** you is already escaped — DataFrame/`GeoDataFrame` cells, the `repr` fallback, and MapLibre tooltip fields. The page `<title>` is escaped too. `golit.escape` is only for the markup you write by hand.

## Sessions & cookies

The session id rides in a cookie named `golit_session`, always set `HttpOnly` (no JS access) and `SameSite=Lax`. `SameSite=Lax` is also the CSRF guard for the state-changing `POST /node` route: a cross-site form submission can't carry the cookie, so it can't drive another user's session.

Behind TLS, also mark the cookie `Secure` so it's never sent over plain HTTP:

```bash
export GOLIT_SECURE_COOKIES=1
```

It defaults off so local `http://` development keeps working.

## Front-end assets: Subresource Integrity

The version-pinned client libraries (htmx + its SSE/WS extensions, Alpine, MapLibre CSS) are served from a CDN with **Subresource Integrity** hashes. The browser refuses to run any of those files if their bytes don't match the embedded `sha384` hash, so a tampered or swapped CDN file can't execute.

To self-host or point at an internal mirror, set the asset origin — it must serve the *same* files, since the SRI hashes still apply:

```bash
export GOLIT_ASSET_BASE=https://assets.internal.example.com
```

Tailwind is the exception: it uses the JIT "play" CDN, which compiles classes in the browser and so can't carry an SRI hash. It's fine for development and many internal apps; for a hardened build, point it at a compiled stylesheet:

```bash
export GOLIT_TAILWIND_SRC=https://assets.internal.example.com/tailwind.css
```

## Authentication

Golit ships **no** auth layer — that's intentionally yours to choose. Instead, `create_app` forwards `middleware`, `guards`, `dependencies`, and `on_app_init` straight to Litestar (which only accepts them at construction time), so you bring your own.

A **guard** is the simplest gate — a callable that runs before every route and aborts by raising:

```python
from golit import App, create_app
from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException
from litestar.handlers.base import BaseRouteHandler

def require_token(connection: ASGIConnection, handler: BaseRouteHandler) -> None:
    if connection.headers.get("x-token") != EXPECTED:
        raise NotAuthorizedException()

litestar_app = create_app(blueprint, guards=[require_token])
```

For real logins (sessions, an identity attached to each request), pass a [Litestar authentication **middleware**](https://docs.litestar.dev/latest/usage/security/) instead — `create_app(blueprint, middleware=[MyAuthMiddleware])` — and it populates `request.user` for your views. For SSO without app code, front the app with a proxy (oauth2-proxy, Cloudflare Access, Tailscale).

## Production checklist

- [ ] Terminate TLS in front of the app, and set `GOLIT_SECURE_COOKIES=1`.
- [ ] Escape untrusted data in hand-written view markup with `golit.escape`.
- [ ] Put an auth layer in front if the data isn't public.
- [ ] (Hardened) self-host assets via `GOLIT_ASSET_BASE` + `GOLIT_TAILWIND_SRC` instead of public CDNs.
- [ ] Run behind a reverse proxy (timeouts, request limits); for multi-worker, set `GOLIT_REDIS_URL` (see [Deployment & scaling](deployment.md)).
