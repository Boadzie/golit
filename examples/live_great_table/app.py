"""Live Great Table — a polished Great Tables display that updates itself as the sheet changes.

The synthesis of two Golit features: `@app.poll` streams a Google Sheet (fetched SSRF-safely),
and the view returns a `great_tables` `GT` object — which Golit auto-renders. When the sheet
changes, golit pushes the re-rendered table over SSE, so a *beautifully formatted* table stays
live with no client code. Point `GOLIT_SHEET_URL` at your own "anyone with the link can view"
sheet (or a direct `.csv`); the default is Google's public sample.

    pip install "golit[tables]"
    golit run examples/live_great_table/app.py
"""

from __future__ import annotations

import io
import ipaddress
import os
import re
import socket
from urllib.parse import urljoin, urlparse

import golit.ui as ui
import httpx
import polars as pl
from golit import App, create_app
from great_tables import GT, md

SHEET_URL = os.environ.get(
    "GOLIT_SHEET_URL",
    "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0",
)
POLL_SECONDS = float(os.environ.get("GOLIT_SHEET_POLL", "3"))

_SHEET_ID = re.compile(r"/spreadsheets/d/([\w-]+)")
_GID = re.compile(r"[#&?]gid=(\d+)")


def _export_url(url: str) -> str:
    parsed = urlparse(url)
    if (parsed.hostname or "") == "docs.google.com" and "/spreadsheets/" in parsed.path:
        match = _SHEET_ID.search(parsed.path)
        if match:
            gid_match = _GID.search(url)
            gid = gid_match.group(1) if gid_match else "0"
            return (
                f"https://docs.google.com/spreadsheets/d/{match.group(1)}"
                f"/export?format=csv&gid={gid}"
            )
    return url


def _check_public(url: str) -> None:
    if os.environ.get("ALLOW_PRIVATE_HOSTS", "").lower() in {"1", "true", "yes"}:
        return
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    for info in socket.getaddrinfo(host, port):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(f"refusing to fetch a non-public host: {host}")


async def _fetch_csv(url: str) -> bytes:
    target = _export_url(url)
    async with httpx.AsyncClient(follow_redirects=False, timeout=15) as client:
        for _ in range(6):
            _check_public(target)
            resp = await client.get(target)
            if resp.is_redirect:
                target = urljoin(target, resp.headers["location"])
                continue
            resp.raise_for_status()
            return resp.content
    raise ValueError("too many redirects")


app = App(title="Live Great Table")


@app.poll("sheet", interval=POLL_SECONDS)
async def sheet() -> pl.DataFrame:
    raw = await _fetch_csv(SHEET_URL)
    return pl.read_csv(
        io.BytesIO(raw), infer_schema_length=2000, truncate_ragged_lines=True
    ).head(500)


@app.view
def report(sheet: pl.DataFrame | None):
    if sheet is None:
        return ui.card(ui.spinner(label="Connecting to the sheet…"), title="Live table")
    numeric = [name for name, dtype in sheet.schema.items() if dtype.is_numeric()]
    gt = GT(sheet).tab_header(
        title="Live sheet", subtitle=f"{sheet.height} rows × {sheet.width} cols"
    )
    if numeric:
        gt = gt.fmt_number(columns=numeric, decimals=2, use_seps=True)
    return gt.tab_source_note(md("Updates live as the sheet changes — `@app.poll` → SSE."))


application = create_app(app)
