"""A minimal app for the cross-node fan-out proof (`deploy/verify_scaling.py`).

One server-side-driven view, `clock`, plus a background ticker that publishes an
`Invalidation(node_id="clock")` to the shared PubSub once a second — but **only** when
`GOLIT_PUBLISH` is set in the environment. That switch is the whole point: run the
publisher on node A (`GOLIT_PUBLISH=1`) and connect a browser/SSE client to node B (no
publisher). If node B's client receives `node:clock` events, the invalidation crossed
Redis from A to B — exactly the horizontal-scale claim in `DEPLOYMENT.md`.

    # both nodes: export GOLIT_REDIS_URL=redis://localhost:6379
    GOLIT_PUBLISH=1 golit run deploy/scaling_demo/app.py --port 8101   # node A (publisher)
                    golit run deploy/scaling_demo/app.py --port 8102   # node B (no publisher)
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import datetime
from typing import Any

from golit import App, create_app
from golit.server.pubsub import Invalidation

app = App(title="Scaling Demo")


@app.view
def clock() -> str:
    # Millisecond precision so each tick's fragment differs — the SSE layer only pushes a
    # node:<id> event when the re-rendered fragment actually changed.
    now = datetime.now().isoformat(timespec="milliseconds")
    return f'<div class="text-2xl font-mono">{now}</div>'


async def _start_ticker(litestar: Any) -> None:
    """Publish a global `clock` invalidation every second — only on the publisher node."""
    if not os.environ.get("GOLIT_PUBLISH"):
        return

    async def tick() -> None:
        while True:
            await asyncio.sleep(1.0)
            await litestar.state.pubsub.publish(Invalidation(node_id="clock", session=None))

    litestar.state.ticker_task = asyncio.create_task(tick())


async def _stop_ticker(litestar: Any) -> None:
    task = getattr(litestar.state, "ticker_task", None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


application = create_app(app, on_startup=[_start_ticker], on_shutdown=[_stop_ticker])
