"""Live Sheets — a Golit dashboard that streams a public Google Sheet as it changes.

`@app.poll` fetches the sheet every few seconds; when its content **hash** changes, Golit pushes
the re-rendered table and chart to every open browser over **SSE** — you write plain views and
they update on their own. Point `GOLIT_SHEET_URL` at your own *"anyone with the link can view"*
sheet (or a direct `.csv` URL) to watch it update live; the default is Google's public sample.

    pip install golit
    golit run examples/live_sheets/app.py

The sheet URL is fetched defensively (SSRF-guarded: public hosts only). For local testing
against a sheet on `localhost`, set `ALLOW_PRIVATE_HOSTS=true` — never in production.
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
from golit.charts import aes, geom_bar, ggplot, ggsize

SHEET_URL = os.environ.get(
    "GOLIT_SHEET_URL",
    "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0",
)
POLL_SECONDS = float(os.environ.get("GOLIT_SHEET_POLL", "3"))
MAX_ROWS = 2000

_SHEET_ID = re.compile(r"/spreadsheets/d/([\w-]+)")
_GID = re.compile(r"[#&?]gid=(\d+)")


def _export_url(url: str) -> str:
    """A Google Sheets link → its public CSV export; other URLs pass through."""
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
    """Refuse internal targets (SSRF guard); opt out with ALLOW_PRIVATE_HOSTS for local tests."""
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
            _check_public(target)  # re-checked at every redirect hop
            resp = await client.get(target)
            if resp.is_redirect:
                target = urljoin(target, resp.headers["location"])
                continue
            resp.raise_for_status()
            return resp.content
    raise ValueError("too many redirects")


app = App(title="Live Sheets")


@app.poll("sheet", interval=POLL_SECONDS)
async def sheet() -> pl.DataFrame:
    """Fetch the sheet. Runs every POLL_SECONDS; Golit pushes an update only on a hash change."""
    raw = await _fetch_csv(SHEET_URL)
    return pl.read_csv(
        io.BytesIO(raw), infer_schema_length=2000, truncate_ragged_lines=True
    ).head(MAX_ROWS)


def _pick(df: pl.DataFrame) -> tuple[str | None, str | None]:
    """A category column (first non-numeric) and a metric column (first numeric)."""
    numeric = [name for name, dtype in df.schema.items() if dtype.is_numeric()]
    category = [c for c in df.columns if c not in numeric]
    return (category[0] if category else None), (numeric[0] if numeric else None)


@app.view
def live_table(sheet: pl.DataFrame | None) -> str:
    if sheet is None:
        return ui.card(ui.spinner(label="Connecting to the sheet…"), title="Live data")
    return ui.card(
        ui.table(sheet, max_rows=20),
        ui.caption(f"{sheet.height} rows × {sheet.width} cols — updates live as the sheet changes"),
        title="Live data",
    )


@app.view
def live_chart(sheet: pl.DataFrame | None) -> str:
    if sheet is None:
        return ui.card(ui.skeleton(lines=4), title="Chart")
    cat, metric = _pick(sheet)
    if not cat or not metric:
        return ui.card(
            ui.caption("Need a text column and a numeric column to chart."), title="Chart"
        )
    agg = (
        sheet.group_by(cat).agg(pl.col(metric).sum()).sort(metric, descending=True).head(12)
    )
    plot = ggplot(agg, aes(cat, metric)) + geom_bar(stat="identity") + ggsize(640, 340)
    return ui.card(plot, title=f"{metric} by {cat}")


application = create_app(app)
