"""The shared :class:`App` instance.

It lives alone in its own module so that `sources`, `reactives`, and `views` can each
`from _app import app` and register on the **same** instance — Python imports a module once
and caches it, so there's exactly one `app`. Keeping nothing else here avoids import cycles
(this module imports only golit; the node modules import this one).
"""

from __future__ import annotations

from golit import App

app = App(title="Modular Dashboard")
