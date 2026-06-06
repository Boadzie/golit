# Modular app

The same reactive dashboard you'd write in one `app.py`, but split across modules — how a
larger Golit project is organized.

```
modular/
  _app.py       # the shared App instance — app = App(...)
  sources.py    # @app.source   — data into the graph
  reactives.py  # @app.reactive — transforms + a slider input
  views.py      # @app.view     — the rendered fragments
  app.py        # entrypoint: imports the above, then create_app(app)
```

Run it:

```bash
golit run examples/modular/app.py
# open http://127.0.0.1:8000
```

## Why this works

`@app.source` / `@app.reactive` / `@app.view` register a node on the `app` instance **the
moment the decorator runs** — i.e. when the module is imported. So splitting across files needs
just two things:

1. **One shared `app`.** It lives alone in [`_app.py`](_app.py); every node module does
   `from _app import app`. Python imports a module once and caches it, so all four files
   decorate the *same* instance.
2. **The entrypoint imports every node module** ([`app.py`](app.py)) before calling
   `create_app(app)`. Importing is what runs the decorators; `create_app` then resolves the
   whole graph. A view in `views.py` depends on a reactive in `reactives.py` *by parameter
   name* — Golit wires it across modules; the file boundaries are invisible to the graph.

## The one wrinkle: `golit run` and `sys.path`

`golit run app.py` executes that single file directly (not as a package), so a bare
`import sources` wouldn't find the siblings from an arbitrary working directory. `app.py` fixes
that by putting its own folder on `sys.path` first:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
```

## For an installable project

Prefer a real Python **package** with relative imports (`from .app import app`) and serve the
import string with any ASGI server — no `sys.path` line:

```bash
uvicorn myapp.main:application
```

See [Running your app → Splitting across modules](../../docs/tutorial/running.md) for both
layouts side by side.
