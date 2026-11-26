"""Optional headless browser (Playwright) for the agent, with visible panel and HTTP fallback.

If Playwright is missing or fails, falls back to plain HTTP fetch + request log.
NetGuard is always applied. User can hide the live view (session flag).
"""
from __future__ import annotations

import os
import threading
from typing import Any

from . import netguard

_browser = None
_lock = threading.Lock()
_visible = True          # session flag: show live view or not
_log: list[dict] = []    # recent requests for the log view
MAX_LOG = 40


def set_visible(v: bool) -> None:
    global _visible
    _visible = bool(v)


def is_visible() -> bool:
    return _visible


def log_request(url: str, status: str = "ok") -> None:
    _log.append({"url": url, "status": status})
    if len(_log) > MAX_LOG:
        del _log[:len(_log) - MAX_LOG]


def recent_log() -> list[dict]:
    return list(_log)


def _try_playwright():
    global _browser
    if _browser is not None:
        return _browser
    try:
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        _browser = p.chromium.launch(headless=True)
        return _browser
    except Exception:
        return None


def fetch_page(url: str, timeout: float = 20.0) -> tuple[str, str]:
    """Return (content_type, text). Uses Playwright if available and visible, else HTTP."""
    try:
        netguard.check_url(url)
    except netguard.BlockedURL as e:
        raise ValueError(str(e))

    if is_visible():
        br = _try_playwright()
        if br is not None:
            try:
                page = br.new_page()
                page.goto(url, timeout=int(timeout * 1000), wait_until="domcontentloaded")
                text = page.content()
                page.close()
                log_request(url, "browser")
                return "text/html", text
            except Exception as e:
                log_request(url, f"browser-fail:{type(e).__name__}")
                # fall through to HTTP
    # HTTP fallback
    import urllib.request
    from . import USER_AGENT
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with netguard.open_url(req, timeout) as r:
        body = r.read(2_000_000).decode("utf-8", "replace")
        ctype = r.headers.get("Content-Type", "text/plain")
    log_request(url, "http")
    return ctype, body
