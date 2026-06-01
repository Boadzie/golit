"""HTTP routes.

- ``GET /`` renders the full page (controls + every view) for a session.
- ``POST /node/{input_id}`` commits an input change, runs the dirty subgraph, and
  returns *only* the changed view fragments as out-of-band HTMX swaps.
- ``GET /events`` (the SSE push channel) is added in M5.
"""

from __future__ import annotations

from litestar import Request, get, post
from litestar.datastructures import Cookie
from litestar.enums import MediaType
from litestar.exceptions import NotFoundException
from litestar.params import FromPath
from litestar.response import Response, ServerSentEvent

from ..engine import Session
from ..nodes import NodeKind
from ..rendering import controls_panel, oob_fragment, page, view_slot
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
    controls = [session.control_html(input_id) for input_id in session.app.widgets]
    views = [
        view_slot(node_id, session.fragment(node_id) or "")
        for node_id, ndef in session.app.node_defs.items()
        if ndef.kind is NodeKind.VIEW
    ]
    return controls_panel(controls) + '<div class="space-y-8">' + "".join(views) + "</div>"


@get("/", media_type=MediaType.HTML)
async def index(request: Request) -> Response:
    sid, session, created = _manager(request).get_or_create(request.cookies.get(COOKIE))
    if created:
        session.initial_render()
    return _html(page(session.app.title, _layout(session)), sid, created)


@post("/node/{input_id:str}", media_type=MediaType.HTML, status_code=200)
async def update_node(input_id: FromPath[str], request: Request) -> Response:
    sid, session, created = _manager(request).get_or_create(request.cookies.get(COOKIE))
    if created:
        session.initial_render()

    form = await request.form()
    raw = form.get("value")
    if raw is not None and hasattr(raw, "read"):
        raw = await raw.read()  # multipart UploadFile -> bytes

    try:
        fragments = session.update(input_id, raw)
    except KeyError as exc:
        raise NotFoundException(f"no such input: {input_id!r}") from exc

    body = "".join(oob_fragment(node_id, content) for node_id, content in fragments.items())
    return _html(body, sid, created)


@get("/events")
async def events(request: Request) -> ServerSentEvent:
    """The server→client push channel: one long-lived SSE stream per session,
    emitting a named ``node:<id>`` event per dirty view fragment."""
    manager = _manager(request)
    sid = request.cookies.get(COOKIE)
    if manager.get(sid) is None:
        sid, session, _ = manager.get_or_create(sid)
        session.initial_render()
    assert sid is not None
    sse: SSEManager = request.app.state.sse
    return ServerSentEvent(sse.stream(sid))
