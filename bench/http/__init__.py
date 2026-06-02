"""End-to-end HTTP benchmark: B1 over Golit's real POST transport.

Boots a synthetic Golit app under uvicorn and drives ``POST /node/<input>`` with
an HTTP client, measuring input → fragment latency over the wire (the in-process
:mod:`bench.run_b1` excludes HTTP framing, the HTMX-swap payload, and ASGI
overhead). Also records bytes-per-update — B3.
"""
