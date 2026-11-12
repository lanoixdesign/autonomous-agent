"""Append-only audit log (JSON Lines). One line per tool call, secrets redacted."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .redact import redact

PREVIEW = 500
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    """One lock per audit file, shared by every AuditLog instance (thread-safe writes)."""
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _short(v: Any, n: int = PREVIEW) -> Any:
    if isinstance(v, str) and len(v) > n:
        return v[:n] + f"... [{len(v) - n} more chars]"
    if isinstance(v, dict):
        return {k: _short(x, n) for k, x in v.items()}
    if isinstance(v, list):
        return [_short(x, n) for x in v]
    return v


class AuditLog:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = _lock_for(self.path)

    def record(self, **entry: Any) -> dict:
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **entry}
        safe = redact(_short(entry))
        line = json.dumps(safe, ensure_ascii=False)
        # O_APPEND: the file is only ever appended to, never rewritten.
        with self._lock:
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, (line + "\n").encode("utf-8"))
            finally:
                os.close(fd)
        return safe

    def tail(self, n: int = 20) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
        return [json.loads(x) for x in lines if x.strip()]
