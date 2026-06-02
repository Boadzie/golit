"""WebSocket chat: the ChatHub fan-out logic, message escaping, and the live
``/ws/<channel>`` route end to end."""

from __future__ import annotations

import golit.ui as ui
from golit import App, create_app
from golit.server import ChatHub, ChatMessage
from litestar.testing import TestClient

# -- hub fan-out --------------------------------------------------------------


async def test_broadcast_reaches_all_connections():
    hub = ChatHub()
    a = hub.join("room", "s1")
    b = hub.join("room", "s2")
    await hub.broadcast("room", ChatMessage("room", "Ada", "hello"))
    fa = a.queue.get_nowait()
    fb = b.queue.get_nowait()
    assert "hello" in fa and "Ada" in fa
    assert fa == fb  # everyone gets the same append fragment
    assert "beforeend:#golit-chat-room-log" in fa


async def test_reply_targets_only_the_sender():
    hub = ChatHub()
    a = hub.join("room", "s1")
    b = hub.join("room", "s2")
    await hub.reply("room", "s1", ChatMessage("room", "Bot", "psst"))
    assert a.queue.qsize() == 1
    assert b.queue.qsize() == 0


async def test_history_is_kept_in_order():
    hub = ChatHub()
    await hub.broadcast("room", ChatMessage("room", "Ada", "one"))
    await hub.broadcast("room", ChatMessage("room", "Bo", "two"))
    assert [m.text for m in hub.history("room")] == ["one", "two"]


async def test_message_text_is_escaped():
    hub = ChatHub()
    c = hub.join("room", "s1")
    await hub.broadcast("room", ChatMessage("room", "x", "<script>alert(1)</script>"))
    frag = c.queue.get_nowait()
    assert "<script>" not in frag
    assert "&lt;script&gt;" in frag


async def test_leave_drops_the_connection():
    hub = ChatHub()
    a = hub.join("room", "s1")
    b = hub.join("room", "s2")
    hub.leave(a)
    await hub.broadcast("room", ChatMessage("room", "x", "hi"))
    assert a.queue.empty()
    assert b.queue.qsize() == 1


# -- inbound routing ----------------------------------------------------------


async def test_relays_to_room_without_a_handler():
    hub = ChatHub(App(title="t"))
    c = hub.join("general", "s1")
    await hub.handle_incoming("general", "s1", {"message": "hi", "author": "Tester"})
    frag = c.queue.get_nowait()
    assert "hi" in frag and "Tester" in frag


async def test_handler_owns_the_message():
    app = App(title="t")
    seen: list[str] = []

    @app.on_message("general")
    async def handle(msg, ctx):
        seen.append(msg.text)
        await ctx.reply("ack", author="Bot")  # reply, no relay

    hub = ChatHub(app)
    c = hub.join("general", "s1")
    await hub.handle_incoming("general", "s1", {"message": "yo"})
    assert seen == ["yo"]
    frags = []
    while not c.queue.empty():
        frags.append(c.queue.get_nowait())
    assert len(frags) == 1 and "ack" in frags[0]  # only the reply, default relay suppressed


async def test_blank_message_is_ignored():
    hub = ChatHub(App(title="t"))
    c = hub.join("general", "s1")
    await hub.handle_incoming("general", "s1", {"message": "   "})
    assert c.queue.empty()


# -- the live route -----------------------------------------------------------


def build_chat_app():
    app = App(title="Chat")

    @app.view
    def room() -> str:
        return ui.chat("general", title="Room")

    return create_app(app)


def test_page_includes_chat_mount_and_ws_extension():
    with TestClient(app=build_chat_app()) as client:
        body = client.get("/").text
        assert 'ws-connect="/ws/general"' in body
        assert "htmx-ext-ws" in body
        assert 'id="golit-chat-general-log"' in body


def test_websocket_broadcasts_message_back():
    with TestClient(app=build_chat_app()) as client:
        with client.websocket_connect("/ws/general") as ws:
            ws.send_json({"message": "hello", "author": "Tester"})
            data = ws.receive_text()
    assert "hello" in data and "Tester" in data
    assert "beforeend:#golit-chat-general-log" in data
