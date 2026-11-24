"""v0.9.14: the app in its own window (pywebview: WKWebView on macOS, Edge WebView2 on Windows).

The local server is unchanged; the window only loads http://127.0.0.1:<port>/. Closing the window stops the
app. No pywebview (running from source), no WebView2, no GUI toolkit, or --browser / AGENT_BROWSER=1:
the browser opens as before and the reason is logged.
"""
from __future__ import annotations

import os
import sys
from typing import Callable

TITLE = "AutonomousAgent"
SIZE = (1100, 750)
MIN_SIZE = (720, 520)


def wanted(argv: list[str]) -> tuple[bool, list[str]]:
    """(use a window?, argv without --browser). AGENT_BROWSER=1 or --browser forces the browser."""
    rest = [a for a in argv if a != "--browser"]
    if len(rest) != len(argv) or os.environ.get("AGENT_BROWSER", "").strip().lower() in ("1", "true", "yes", "on"):
        return False, rest
    if os.environ.get("AGENT_NO_BROWSER") == "1":      # tests / CI smoke: nothing on screen
        return False, rest
    return True, rest


def load() -> tuple[object | None, str]:
    """(webview module, "") or (None, why)."""
    try:
        import webview  # type: ignore
    except Exception as e:  # noqa: BLE001 - not installed (source run) or a broken backend
        return None, f"pywebview not available ({type(e).__name__}: {e})"
    return webview, ""


def run(webview, url: str, on_closed: Callable[[], None], watch: Callable[[Callable[[], None]], None] | None = None,
        log: Callable[[str], None] = lambda m: None) -> bool:
    """Open the window and block until it is closed (must run on the main thread). True if it opened.
    on_closed: called when the user closes the window (stops the server).
    watch(close): started in a thread with a function that closes the window (server stopped by itself)."""
    try:
        try:
            webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True    # Groq console, docs… -> system browser
            webview.settings["ALLOW_DOWNLOADS"] = True                   # exports / attachments
        except Exception:  # noqa: BLE001 - older pywebview
            pass
        win = webview.create_window(TITLE, url, width=SIZE[0], height=SIZE[1], min_size=MIN_SIZE, resizable=True,
                                    text_select=True)
        user_closed = [True]

        def close_from_server():
            user_closed[0] = False
            try:
                win.destroy()
            except Exception:  # noqa: BLE001
                pass
        win.events.closed += lambda: on_closed() if user_closed[0] else None
        args = {}
        if watch is not None:
            args = {"func": watch, "args": (close_from_server,)}
        webview.start(**args)
        return True
    except Exception as e:  # noqa: BLE001 - WebView2 missing, no GUI…: caller falls back to the browser
        log(f"window: could not open ({type(e).__name__}: {e}); using the browser")
        return False


def describe() -> str:
    wv, why = load()
    if wv is None:
        return "window: " + why
    msg = f"window: pywebview available ({sys.platform})"
    if os.environ.get("AGENT_SMOKE") == "1":      # CI smoke test: the platform backend is bundled too
        mod = {"darwin": "webview.platforms.cocoa", "win32": "webview.platforms.winforms"}.get(sys.platform)
        if mod:
            try:
                __import__(mod)
                msg += f"; backend {mod.rsplit('.', 1)[1]} ok"
            except Exception as e:  # noqa: BLE001
                msg += f"; backend {mod.rsplit('.', 1)[1]} FAILED ({type(e).__name__}: {e})"
    return msg
