"""Harness persistence (stdlib sqlite3): conversations, their events, schedules and approval rules.

One file (default <state-dir>/harness.sqlite3). Everything is stored as JSON, already redacted by the
caller. Thread-safe: one connection, one lock. Restored when the harness starts again.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any

TABLES = ("tasks", "schedules", "rules", "settings")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks     (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedules (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rules     (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings  (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events    (task_id TEXT NOT NULL, seq INTEGER NOT NULL, data TEXT NOT NULL,
                                      PRIMARY KEY (task_id, seq));
"""


def _loads(blob: Any) -> Any:
    """A row written by an older (or interrupted) version that is not valid JSON is skipped."""
    try:
        return json.loads(blob)
    except (TypeError, ValueError):
        return None


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.backup: Path | None = None
        try:
            self._open()
        except sqlite3.DatabaseError as e:
            # v0.9.13: a damaged file (crash, disk full, other program) must not stop the app starting:
            # it is kept aside (harness.sqlite3.broken-<date>) and a new empty one is created.
            self.backup = self.path.with_name(f"{self.path.name}.broken-{time.strftime('%Y%m%d-%H%M%S')}")
            print(f"warning: {self.path.name} could not be opened ({e}); kept as {self.backup.name}, "
                  "starting with an empty history", file=sys.stderr)
            for suffix in ("", "-wal", "-shm"):
                src = Path(str(self.path) + suffix)
                if src.exists():
                    os.replace(src, Path(str(self.backup) + suffix))
            self._open()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _open(self) -> None:
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        try:
            with self._lock:
                self._db.execute("PRAGMA journal_mode=WAL")
                self._db.executescript(SCHEMA)
                self._db.execute("SELECT count(*) FROM tasks").fetchone()
        except sqlite3.DatabaseError:
            self._db.close()
            raise

    def put(self, table: str, id: str, data: dict) -> None:
        if table not in TABLES:
            raise ValueError(f"unknown table: {table!r}")
        blob = json.dumps(data, ensure_ascii=False)
        with self._lock:
            self._db.execute(f"INSERT OR REPLACE INTO {table} (id, data) VALUES (?, ?)", (id, blob))

    def delete(self, table: str, id: str) -> None:
        if table not in TABLES:
            raise ValueError(f"unknown table: {table!r}")
        with self._lock:
            self._db.execute(f"DELETE FROM {table} WHERE id = ?", (id,))
            if table == "tasks":
                self._db.execute("DELETE FROM events WHERE task_id = ?", (id,))

    def all(self, table: str) -> list[dict]:
        if table not in TABLES:
            raise ValueError(f"unknown table: {table!r}")
        with self._lock:
            rows = self._db.execute(f"SELECT data FROM {table} ORDER BY rowid").fetchall()
        return [d for d in (_loads(r[0]) for r in rows) if isinstance(d, dict) and "id" in d]

    def add_event(self, task_id: str, seq: int, data: dict[str, Any]) -> None:
        blob = json.dumps(data, ensure_ascii=False)
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO events (task_id, seq, data) VALUES (?, ?, ?)",
                             (task_id, seq, blob))

    def events(self, task_id: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM events WHERE task_id = ? ORDER BY seq", (task_id,)).fetchall()
        return [d for d in (_loads(r[0]) for r in rows) if isinstance(d, dict)]

    def close(self) -> None:
        with self._lock:
            self._db.close()
