"""Chat — a WebSocket-backed chat room.

A multi-user room: every message relays to all connected clients (open the app in
two browser tabs to watch it sync). An ``@app.on_message`` handler adds a tiny bot —
type ``/bot <text>`` and it replies just to you, showing the room-broadcast +
handler-hook model.

The chat rides HTMX's ``ws`` extension and server-rendered fragments — same "the
wire format is the UI" idea as the rest of Golit, just bidirectional.

    golit run examples/chat/app.py
"""

from __future__ import annotations

import golit.ui as ui
from golit import App, create_app

app = App(title="Chat")


@app.view
def room() -> str:
    return ui.chat("general", title="Team chat", placeholder="Say hello…  (try /bot hi)")


@app.on_message("general")
async def on_message(msg, ctx) -> None:
    # Relay every message to the whole room…
    await ctx.broadcast(msg.text, author=msg.author)
    # …and answer "/bot ..." just for the sender.
    if msg.text.lower().startswith("/bot"):
        await ctx.reply("🤖 " + (msg.text[4:].strip() or "hello!"), author="Bot")


application = create_app(app)
