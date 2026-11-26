"""Telegram bot bridge: receives messages, forwards them to the local agent, replies.

Configure with TELEGRAM_BOT_TOKEN (or set it in Settings later).
Long replies are split. /log returns the recent action log of the current session.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import netguard

MAX_TG = 4000          # Telegram message limit (safe margin)
API = "https://api.telegram.org/bot"


def _token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or None


def _call(method: str, **params: Any) -> dict:
    tok = _token()
    if not tok:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    url = f"{API}{tok}/{method}"
    data = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with netguard.open_url(req, 30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        raise RuntimeError(f"Telegram {method} failed: {e}")


def send(chat_id: int | str, text: str) -> None:
    """Send text, splitting if longer than MAX_TG."""
    text = text or "(empty)"
    for i in range(0, len(text), MAX_TG):
        _call("sendMessage", chat_id=chat_id, text=text[i:i + MAX_TG])


class TelegramBridge:
    def __init__(self, harness: Any, poll: float = 2.0):
        self.h = harness
        self.poll = poll
        self._offset = 0
        self._thread: threading.Thread | None = None
        self._stop = False
        self._sessions: dict[int, str] = {}   # chat_id -> task_id

    def start(self) -> None:
        if not _token() or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="telegram")
        self._thread.start()

    def stop(self) -> None:
        self._stop = True

    def _loop(self) -> None:
        while not self._stop:
            try:
                updates = _call("getUpdates", offset=self._offset, timeout=20).get("result") or []
                for u in updates:
                    self._offset = u["update_id"] + 1
                    self._handle(u)
            except Exception:
                time.sleep(self.poll)
            time.sleep(0.2)

    def _handle(self, u: dict) -> None:
        msg = u.get("message") or {}
        chat = msg.get("chat", {}).get("id")
        text = (msg.get("text") or "").strip()
        if not chat or not text:
            return
        if text == "/log":
            send(chat, self._log(chat))
            return
        if text.startswith("/"):
            send(chat, "Commands: /log (recent actions)")
            return
        # Forward to agent
        try:
            tid = self._sessions.get(chat)
            if tid is None:
                task = self.h.submit(text, source="telegram")
                tid = task.id
                self._sessions[chat] = tid
            else:
                self.h.send(tid, text)
            time.sleep(2)
            task = self.h._tasks.get(tid)
            reply = getattr(task, "result", None) or "..."
            send(chat, str(reply)[:MAX_TG * 2])
        except Exception as e:
            send(chat, f"Error: {e}")

    def _log(self, chat: int) -> str:
        tid = self._sessions.get(chat)
        if not tid:
            return "No session yet."
        try:
            tid = self._sessions.get(chat)
            if not tid:
                return "No session yet."
            task = self.h._tasks.get(tid)
            events = getattr(task, "events", [])[-20:]
            lines = [f"{e.get('kind','?')} {(e.get('content') or e.get('text') or '')[:120]}" for e in events]
            return "\n".join(lines) or "(no events)"
        except Exception:
            return "(log unavailable)"
