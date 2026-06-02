"""WebSocket chat — the bidirectional channel.

SSE (``golit.server.sse``) is the server→client *push* channel for reactive
invalidations. Chat is the one case Golit's design doc names as worth a real
WebSocket: genuinely bidirectional, low-latency messaging. It stays Golit-native —
the wire format is still *server-rendered HTML fragments*, just two-way:

- The client connects with HTMX's ``ws`` extension (``ws-connect="/ws/<channel>"``)
  and sends form fields over the socket (``ws-send``).
- The server renders each message to an out-of-band append fragment and broadcasts
  it to every connection on the channel; HTMX swaps it into the chat log by id.

Routing model — **room broadcast + an optional handler hook**:

- No handler registered for a channel → every message relays to all connections on
  it (a multi-user room).
- An ``@app.on_message(channel)`` handler registered → it *owns* the message and
  decides what to send, via :class:`MessageContext` (``broadcast`` to the room,
  ``reply`` only to the sender). This covers bots, assistants, and moderation.

Single-node for now: broadcast is in-process across one worker's connections, behind
the same seam SSE uses — a Redis-backed fan-out drops in later to span a fleet.
"""

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from ..widgets import esc


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One chat message: which ``channel`` it belongs to, who sent it, and the text."""

    channel: str
    author: str
    text: str


class ChatConnection:
    """One open WebSocket on a channel. Carries an outbound queue (drained to the
    socket by the route), so broadcasts never write to a socket concurrently."""

    __slots__ = ("channel", "session", "queue")

    def __init__(self, channel: str, session: str | None) -> None:
        self.channel = channel
        self.session = session
        self.queue: asyncio.Queue[str] = asyncio.Queue()


class MessageContext:
    """Handed to an ``@app.on_message`` handler so it can respond to a message."""

    def __init__(self, hub: ChatHub, channel: str, session: str | None) -> None:
        self._hub = hub
        #: The channel the message arrived on.
        self.channel = channel
        #: The sender's session id (used to target :meth:`reply`).
        self.session = session

    async def broadcast(self, text: Any, *, author: str = "Bot") -> None:
        """Send a message to **everyone** on the channel (and into its history)."""
        await self._hub.broadcast(self.channel, ChatMessage(self.channel, author, str(text)))

    async def reply(self, text: Any, *, author: str = "Bot") -> None:
        """Send a message back to **only the sender's** connections (not stored in
        history, so other clients never see it)."""
        msg = ChatMessage(self.channel, author, str(text))
        await self._hub.reply(self.channel, self.session, msg)


def render_message(msg: ChatMessage) -> str:
    """Render a message to a chat bubble (author label + escaped text)."""
    return (
        '<div class="golit-chat-msg flex flex-col gap-0.5 px-3 py-2 rounded-lg '
        'bg-surface-container-low">'
        '<span class="text-[10px] font-semibold uppercase tracking-wider text-primary">'
        f"{esc(msg.author)}</span>"
        f'<span class="text-sm text-on-surface break-words">{esc(msg.text)}</span></div>'
    )


def message_oob(msg: ChatMessage) -> str:
    """Wrap a bubble as an out-of-band append into the channel's log element, so
    HTMX's ws extension swaps it in by id on every connected client."""
    return (
        f'<div hx-swap-oob="beforeend:#golit-chat-{esc(msg.channel)}-log">'
        f"{render_message(msg)}</div>"
    )


class ChatHub:
    """Tracks open connections per channel, keeps a short history, and fans messages
    out. Holds no sockets — only outbound queues — so it is trivially testable and
    the transport (the WebSocket route) stays separate."""

    def __init__(self, app: Any = None, *, history: int = 50) -> None:
        self._app = app
        self._conns: dict[str, list[ChatConnection]] = defaultdict(list)
        self._history: dict[str, deque[ChatMessage]] = defaultdict(lambda: deque(maxlen=history))

    # -- connection registry ----------------------------------------------
    def join(self, channel: str, session: str | None) -> ChatConnection:
        conn = ChatConnection(channel, session)
        self._conns[channel].append(conn)
        return conn

    def leave(self, conn: ChatConnection) -> None:
        conns = self._conns.get(conn.channel)
        if conns and conn in conns:
            conns.remove(conn)
        if conns is not None and not conns:
            del self._conns[conn.channel]

    def history(self, channel: str) -> list[ChatMessage]:
        """The recent messages on a channel, oldest first (replayed to a joiner)."""
        return list(self._history[channel])

    # -- fan-out ----------------------------------------------------------
    async def broadcast(self, channel: str, msg: ChatMessage) -> None:
        """Store ``msg`` in history and enqueue it for every connection on the channel."""
        self._history[channel].append(msg)
        frag = message_oob(msg)
        for conn in self._conns.get(channel, []):
            conn.queue.put_nowait(frag)

    async def reply(self, channel: str, session: str | None, msg: ChatMessage) -> None:
        """Enqueue ``msg`` only for connections owned by ``session`` (no history)."""
        frag = message_oob(msg)
        for conn in self._conns.get(channel, []):
            if conn.session == session:
                conn.queue.put_nowait(frag)

    # -- inbound ----------------------------------------------------------
    async def handle_incoming(
        self, channel: str, session: str | None, data: dict[str, Any]
    ) -> None:
        """Process a raw inbound payload from a client (the form fields HTMX sent).

        With no handler for the channel, the message relays to the room. With a
        handler, it owns the message via :class:`MessageContext`."""
        text = str(data.get("message", "")).strip()
        if not text:
            return
        author = str(data.get("author") or _guest(session))
        msg = ChatMessage(channel, author, text)

        handler = self._handler_for(channel)
        if handler is None:
            await self.broadcast(channel, msg)
            return
        result = handler(msg, MessageContext(self, channel, session))
        if inspect.isawaitable(result):
            await result

    def _handler_for(self, channel: str) -> Any:
        handlers = getattr(self._app, "chat_handlers", {}) or {}
        return handlers.get(channel) or handlers.get(None)


def _guest(session: str | None) -> str:
    return f"guest-{session[:4]}" if session else "guest"
