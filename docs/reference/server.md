# Server

The Litestar orchestrator that hosts a Golit app. See [Running your app](../tutorial/running.md), [Server-push updates](../advanced/server-push.md), and [Deployment & scaling](../advanced/deployment.md).

## create_app

::: golit.server.factory.create_app

::: golit.server.factory.pubsub_from_env

## Invalidation & pub/sub

The SSE fan-out channel. `Invalidation` is the unit published when a node goes dirty server-side; `PubSub` is the protocol both backends implement.

::: golit.server.pubsub.Invalidation

::: golit.server.pubsub.PubSub

::: golit.server.pubsub.InMemoryPubSub

::: golit.server.redis_pubsub.RedisPubSub

## Sessions & SSE

::: golit.server.session.SessionManager

::: golit.server.sse.SSEManager

## Chat

The WebSocket chat channel. See [WebSocket chat](../advanced/websockets.md).

::: golit.server.chat.ChatMessage

::: golit.server.chat.MessageContext

::: golit.server.chat.ChatHub

## Kernel version

`golit.kernel_version()` returns the version string of the compiled Rust kernel (`golit._golit`). It's a plain function with no arguments:

```python
import golit

golit.kernel_version()   # e.g. "0.1.0"
```
