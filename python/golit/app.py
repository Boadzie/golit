"""The :class:`App` blueprint.

An ``App`` collects node definitions from the ``@app.source`` / ``@app.reactive``
/ ``@app.view`` decorators and resolves the dependency graph. It is an immutable
*blueprint*: each client session instantiates its own kernel :class:`Graph` and
:class:`~golit.registry.Registry` from it (state is per-session; topology is shared).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from golit._golit import Graph

from .nodes import NodeDef, NodeKind, inspect_params
from .widgets import Widget

NodeFn = Callable[..., Any]


class App:
    def __init__(self, title: str = "Golit App") -> None:
        self.title = title
        self._defs: dict[str, NodeDef] = {}
        self._order: list[str] = []
        self._widgets: dict[str, Widget] = {}
        self._chat_handlers: dict[str | None, NodeFn] = {}
        self._streams: dict[str, NodeFn] = {}
        self._frame_handlers: dict[str, NodeFn] = {}
        self._built = False
        #: Optional page layout tree (see :mod:`golit.layout`); ``None`` stacks
        #: every view under one controls panel.
        self.layout: Any = None

    # -- registration ------------------------------------------------------
    def _register(self, fn: NodeFn, kind: NodeKind) -> NodeFn:
        node_id = fn.__name__
        if node_id in self._defs:
            raise ValueError(f"duplicate node {node_id!r}")
        params = inspect_params(fn)
        self._defs[node_id] = NodeDef(id=node_id, kind=kind, fn=fn, params=params)
        self._order.append(node_id)
        for p in params:
            if p.widget is not None:
                p.widget.bind(p.name)
                self._widgets.setdefault(p.name, p.widget)
        self._built = False
        return fn

    def source(self, fn: NodeFn) -> NodeFn:
        """Register a **source** node (brings data in — read a file, query a DB,
        return a sample frame). May depend on inputs. Returns ``fn`` unchanged."""
        return self._register(fn, NodeKind.SOURCE)

    def reactive(self, fn: NodeFn) -> NodeFn:
        """Register a **reactive** node — a pure transform over its upstream nodes
        and inputs. Re-runs only when one of those changes. Returns ``fn`` unchanged."""
        return self._register(fn, NodeKind.REACTIVE)

    def view(self, fn: NodeFn) -> NodeFn:
        """Register a **view** node — a renderable leaf whose return value Golit
        turns into a UI fragment. Re-renders only when an input changes. Returns
        ``fn`` unchanged."""
        return self._register(fn, NodeKind.VIEW)

    def on_message(self, channel: Any = None) -> Any:
        """Register a handler for incoming chat messages on ``channel`` (or all
        channels when ``None``). Without a handler a channel simply relays every
        message to the room; with one, the handler owns the message and responds
        via the :class:`~golit.server.chat.MessageContext` it's given::

            @app.on_message("room")
            async def handle(msg, ctx):
                await ctx.broadcast(msg.text, author=msg.author)   # relay
                if msg.text.startswith("/bot"):
                    await ctx.reply("beep boop", author="Bot")     # to sender only

        Usable bare (``@app.on_message``) or with a channel (``@app.on_message("room")``).
        The handler may be sync or async."""
        if callable(channel):  # used bare: @app.on_message
            self._chat_handlers[None] = channel
            return channel

        def deco(fn: NodeFn) -> NodeFn:
            self._chat_handlers[channel] = fn
            return fn

        return deco

    def stream(self, name: str) -> Callable[[NodeFn], NodeFn]:
        """Register a video **frame producer** named ``name``, shown by
        :func:`golit.ui.webcam`. The decorated function returns an iterator of frames —
        JPEG ``bytes`` (e.g. from ``cv2.imencode``) or ``(H, W, 3)`` uint8 RGB arrays
        (encoded for you) — and each request starts a fresh stream that Golit pushes as an
        MJPEG (``multipart/x-mixed-replace``) response off the event loop::

            @app.stream("camera")
            def camera():
                cap = cv2.VideoCapture(0)
                try:
                    while True:
                        ok, frame = cap.read()
                        if not ok:
                            break
                        # ... run your detector and draw on `frame` ...
                        yield cv2.imencode(".jpg", frame)[1].tobytes()
                finally:
                    cap.release()

        Sync or async (``async def`` + ``yield``) producers both work; sync frames are
        pulled in a worker thread so a blocking camera read or model never stalls the loop."""

        def deco(fn: NodeFn) -> NodeFn:
            self._streams[name] = fn
            return fn

        return deco

    def on_frame(self, name: str) -> Callable[[NodeFn], NodeFn]:
        """Register a per-frame **processor** for the browser-camera view named ``name``,
        shown by :func:`golit.ui.camera`. Each frame the visitor's webcam captures is sent up
        (over a WebSocket), decoded to an ``(H, W, 3)`` uint8 RGB array, passed to the handler,
        and the value it returns — an RGB array or JPEG ``bytes`` — is sent back and displayed::

            @app.on_frame("detector")
            def detect(frame):           # frame: (H, W, 3) uint8 RGB
                # ... run your model and draw on a copy of `frame` ...
                return frame             # annotated RGB array (or JPEG bytes)

        Sync or async (``async def``) handlers both work; sync ones (and every JPEG
        decode/encode) run in a worker thread so a heavy model never stalls the loop. One frame
        is in flight at a time — the client waits for each result — so a slow handler simply
        lowers the frame rate instead of building a backlog. The mirror of :meth:`stream`, which
        produces frames on the server; here the browser is the camera and the server transforms."""

        def deco(fn: NodeFn) -> NodeFn:
            self._frame_handlers[name] = fn
            return fn

        return deco

    # -- resolution --------------------------------------------------------
    def build(self) -> None:
        """Resolve every parameter to an input/dependency/constant. Raises if a
        parameter is neither a widget, a known node, nor a defaulted constant."""
        for node_id, ndef in self._defs.items():
            deps: list[str] = []
            for p in ndef.params:
                if p.widget is not None:
                    deps.append(p.name)  # edge to the input node
                elif p.name in self._defs:
                    deps.append(p.name)  # edge to another compute node
                elif p.has_default:
                    continue  # constant kwarg
                else:
                    raise ValueError(
                        f"node {node_id!r}: parameter {p.name!r} is not a known node "
                        f"or widget input (and has no default)"
                    )
            ndef.deps = deps
            if ndef.kind is NodeKind.VIEW:
                ndef.target = node_id
        if self.layout is not None:
            from .layout import validate_layout

            validate_layout(self.layout, self)
        self._built = True

    def new_graph(self) -> Graph:
        """Build a fresh kernel graph for a session (topology only; state is
        reset per session)."""
        if not self._built:
            self.build()
        graph = Graph()
        for input_id in self._widgets:
            graph.add_node(input_id, NodeKind.INPUT.value)
        for node_id, ndef in self._defs.items():
            graph.add_node(node_id, ndef.kind.value)
        for node_id, ndef in self._defs.items():
            if ndef.deps:
                graph.set_deps(node_id, ndef.deps)
        graph.build()
        return graph

    # -- introspection -----------------------------------------------------
    @property
    def compute_ids(self) -> set[str]:
        return set(self._defs)

    @property
    def node_defs(self) -> dict[str, NodeDef]:
        return self._defs

    @property
    def widgets(self) -> dict[str, Widget]:
        return self._widgets

    @property
    def chat_handlers(self) -> dict[str | None, NodeFn]:
        """Registered chat message handlers, keyed by channel (``None`` = all)."""
        return self._chat_handlers

    @property
    def streams(self) -> dict[str, NodeFn]:
        """Registered video frame producers, keyed by stream name."""
        return self._streams

    @property
    def frame_handlers(self) -> dict[str, NodeFn]:
        """Registered browser-camera frame processors, keyed by camera name."""
        return self._frame_handlers

    def node_def(self, node_id: str) -> NodeDef:
        return self._defs[node_id]

    def widget_for(self, input_id: str) -> Widget | None:
        return self._widgets.get(input_id)

    def input_default(self, input_id: str) -> Any:
        return self._widgets[input_id].default
