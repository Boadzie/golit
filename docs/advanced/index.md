# Advanced User Guide

You can build a lot of Golit without anything here. This section is for when you reach past the common case:

<div class="golit-grid" markdown>

<div markdown>
### [Server-push updates (SSE)](server-push.md)
Push fragments to the client without a user interaction — streaming sources, background jobs, and shared nodes, via the pub/sub channel.
</div>

<div markdown>
### [Custom rendering](custom-rendering.md)
Make your own objects renderable with the `__golit_render__` protocol, and control exactly what markup a view emits.
</div>

<div markdown>
### [Sessions & state](sessions.md)
What a session is, where state lives, and the one rule that governs scaling.
</div>

<div markdown>
### [Deployment & scaling](deployment.md)
From a single process to a Redis-backed fleet behind a sticky load balancer.
</div>

</div>

It assumes you're comfortable with the [tutorial](../tutorial/index.md) and have skimmed [How a change flows](../concepts/data-flow.md).
