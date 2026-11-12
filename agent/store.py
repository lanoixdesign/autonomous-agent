"""Harness persistence (stdlib sqlite3): conversations, their events, schedules and approval rules.

One file (default <state-dir>/harness.sqlite3). Everything is stored as JSON, already redacted by the
caller. Thread-safe: one connection, one lock. Restored when the harness starts again.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

TABLES = ("tasks", "schedules", "rules")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks     (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedules (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rules     (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events    (task_id TEXT NOT NULL, seq INTEGER NOT NULL, data TEXT NOT NULL,
                                      PRIMARY KEY (task_id, seq));
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def put(self, table: str, id: str, data: dict) -> None:
        assert table in TABLES
        blob = json.dumps(data, ensure_ascii=False)
        with self._lock:
            self._db.execute(f"INSERT OR REPLACE INTO {table} (id, data) VALUES (?, ?)", (id, blob))

    def delete(self, table: str, id: str) -> None:
        assert table in TABLES
        with self._lock:
            self._db.execute(f"DELETE FROM {table} WHERE id = ?", (id,))
            if table == "tasks":
                self._db.execute("DELETE FROM events WHERE task_id = ?", (id,))

    def all(self, table: str) -> list[dict]:
        assert table in TABLES
        with self._lock:
            rows = self._db.execute(f"SELECT data FROM {table} ORDER BY rowid").fetchall()
        return [json.loads(r[0]) for r in rows]

    def add_event(self, task_id: str, seq: int, data: dict[str, Any]) -> None:
        blob = json.dumps(data, ensure_ascii=False)
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO events (task_id, seq, data) VALUES (?, ?, ?)",
                             (task_id, seq, blob))

    def events(self, task_id: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM events WHERE task_id = ? ORDER BY seq", (task_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._db.close()
