"""HTTP + WebSocket routes.

- ``GET /`` renders the full page (controls + every view) for a session.
- ``POST /node/{input_id}`` commits an input change, runs the dirty subgraph, and
  returns *only* the changed view fragments as out-of-band HTMX swaps.
- ``GET /events`` is the SSE push channel (one stream per session).
- ``WS /ws/{channel}`` is the bidirectional chat channel (see :mod:`golit.server.chat`).
"""

from __future__ import annotations

import asyncio
import secrets

from anyio import to_thread
from litestar import Request, WebSocket, get, post, websocket
from litestar.datastructures import Cookie
from litestar.enums import MediaType
from litestar.exceptions import NotFoundException, WebSocketDisconnect
from litestar.params import FromPath
from litestar.response import Response, ServerSentEvent

from ..engine import Session
from ..nodes import NodeKind
from ..rendering import controls_panel, oob_fragment, page, view_slot
from .chat import ChatHub, message_oob
from .session import COOKIE, SessionManager
from .sse import SSEManager


def _manager(request: Request) -> SessionManager:
    return request.app.state.sessions


def _session_cookie(sid: str) -> list[Cookie]:
    return [Cookie(key=COOKIE, value=sid, httponly=True, samesite="lax", path="/")]


def _html(body: str, sid: str, created: bool) -> Response:
    cookies = _session_cookie(sid) if created else []
    return Response(body, media_type=MediaType.HTML, cookies=cookies)


def _layout(session: Session) -> str:
    app = session.app
    if app.layout is not None:
        from ..layout import render_layout

        return render_layout(app.layout, session)
    controls = [session.control_html(input_id) for input_id in app.widgets]
    views = [
        view_slot(node_id, session.fragment(node_id) or "")
        for node_id, ndef in app.node_defs.items()
        if ndef.kind is NodeKind.VIEW
    ]
    return controls_panel(controls) + '<div class="space-y-8">' + "".join(views) + "</div>"


@get("/", media_type=MediaType.HTML)
async def index(request: Request) -> Response:
    manager = _manager(request)
    cookie_sid = request.cookies.get(COOKIE)
    # Resolve/build/render off the event loop so a cold render doesn't stall the
    # worker; the per-session lock keeps concurrent same-session requests ordered.
    async with manager.lock_for(cookie_sid):
        sid, session, created = await to_thread.run_sync(manager.prepare, cookie_sid)
    return _html(page(session.app.title, _layout(session)), sid, created)


@post("/node/{input_id:str}", media_type=MediaType.HTML, status_code=200)
async def update_node(input_id: FromPath[str], request: Request) -> Response:
    manager = _manager(request)
    cookie_sid = request.cookies.get(COOKIE)

    form = await request.form()
    raw = form.get("value")
    if raw is not None and hasattr(raw, "read"):
        raw = await raw.read()  # multipart UploadFile -> bytes

    # The reactive update is CPU-bound (Polars + render): run it in a thread so it
    # doesn't block the event loop, under the session lock so the in-place kernel
    # graph isn't mutated by two requests at once.
    try:
        async with manager.lock_for(cookie_sid):
            sid, _session, created, fragments = await to_thread.run_sync(
                manager.prepare_and_update, cookie_sid, input_id, raw
            )
    except KeyError as exc:
        raise NotFoundException(f"no such input: {input_id!r}") from exc

    body = "".join(oob_fragment(node_id, content) for node_id, content in fragments.items())
    return _html(body, sid, created)


@get("/events")
async def events(request: Request) -> ServerSentEvent:
    """The server→client push channel: one long-lived SSE stream per session,
    emitting a named ``node:<id>`` event per dirty view fragment."""
    manager = _manager(request)
    cookie_sid = request.cookies.get(COOKIE)
    sid = cookie_sid
    if manager.get(cookie_sid) is None:
        # Reconstruct the session on this worker so SSE dispatch can find it.
        async with manager.lock_for(cookie_sid):
            sid, _session, _ = await to_thread.run_sync(manager.prepare, cookie_sid)
    assert sid is not None
    sse: SSEManager = request.app.state.sse
    return ServerSentEvent(sse.stream(sid))


@websocket("/ws/{channel:str}")
async def chat_ws(socket: WebSocket, channel: FromPath[str]) -> None:
    """The bidirectional chat channel for ``channel``.

    Registers the connection with the :class:`~golit.server.chat.ChatHub`, replays
    recent history, then concurrently drains outbound broadcasts to the socket and
    reads inbound messages until the client disconnects."""
    await socket.accept()
    hub: ChatHub = socket.app.state.chat
    sid = socket.cookies.get(COOKIE) or secrets.token_urlsafe(8)
    conn = hub.join(channel, sid)

    # Replay history first, then start the live pump, so ordering is preserved.
    for msg in hub.history(channel):
        await socket.send_text(message_oob(msg))

    async def drain() -> None:
        while True:
            await socket.send_text(await conn.queue.get())

    pump = asyncio.create_task(drain())
    try:
        while True:
            data = await socket.receive_json()
            await hub.handle_incoming(channel, sid, data)
    except WebSocketDisconnect:
        pass
    finally:
        pump.cancel()
        hub.leave(conn)
