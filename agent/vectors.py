"""Semantic memory (v0.9): embeddings in a local SQLite file (stdlib sqlite3, vectors as float32 blobs,
cosine similarity in plain Python). Nothing to install, no server.

Vectors come from the provider's OpenAI-compatible `/embeddings` endpoint, through a key the user tagged
"Embeddings" in Settings (with an embeddings model, e.g. OpenAI text-embedding-3-small). Without such a key,
memory recall stays the keyword search it always was; with one, recall is hybrid (meaning + keywords)."""
from __future__ import annotations

import array
import json
import math
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

Embedder = Callable[[list[str]], "list[list[float]] | None"]
MAX_BATCH = 32


def pack(vec: list[float]) -> bytes:
    return array.array("f", vec).tobytes()


def unpack(blob: bytes) -> list[float]:
    a = array.array("f")
    a.frombytes(blob)
    return a.tolist()


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class VectorIndex:
    """id -> (text, model, vector). One small table; fine for the few thousand notes of one person."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS vectors (id TEXT PRIMARY KEY, text TEXT NOT NULL, "
                        "model TEXT NOT NULL, dim INTEGER NOT NULL, vec BLOB NOT NULL, ts REAL NOT NULL)")
        self.db.commit()

    def put(self, item_id: str, text: str, model: str, vec: list[float]) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO vectors VALUES (?,?,?,?,?,?)",
                            (item_id, text, model, len(vec), pack(vec), time.time()))
            self.db.commit()

    def get(self, item_id: str, text: str, model: str) -> list[float] | None:
        with self._lock:
            row = self.db.execute("SELECT text, model, vec FROM vectors WHERE id=?", (item_id,)).fetchone()
        if row is None or row[0] != text or row[1] != model:
            return None
        return unpack(row[2])

    def delete_missing(self, keep: set[str]) -> int:
        with self._lock:
            ids = [r[0] for r in self.db.execute("SELECT id FROM vectors")]
            gone = [i for i in ids if i not in keep]
            self.db.executemany("DELETE FROM vectors WHERE id=?", [(i,) for i in gone])
            self.db.commit()
        return len(gone)

    def count(self) -> int:
        with self._lock:
            return int(self.db.execute("SELECT COUNT(*) FROM vectors").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self.db.close()


def openai_embed(base_url: str, model: str, api_key: str | None, texts: list[str], timeout: float = 30.0
                 ) -> tuple[list[list[float]], int]:
    """POST <base_url>/embeddings (OpenAI-compatible). Returns (vectors, tokens used)."""
    body = json.dumps({"model": model, "input": texts}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(base_url.rstrip("/") + "/embeddings", data=body, headers=headers, method="POST")
    from .netguard import open_url             # v0.9.3: the key never follows a redirect to another host
    with open_url(req, timeout, ssrf=False, same_origin_redirects=True) as r:
        data = json.loads(r.read().decode("utf-8"))
    items = sorted(data.get("data") or [], key=lambda d: d.get("index", 0))
    vecs = [[float(x) for x in (d.get("embedding") or [])] for d in items]
    if len(vecs) != len(texts) or not all(vecs):
        raise ValueError("the embeddings answer does not match the request")
    return vecs, int((data.get("usage") or {}).get("total_tokens") or 0)


class RouterEmbedder:
    """Embeddings through the key pool: only keys tagged with the "embeddings" category are used (never a
    chat key as a backup). Returns None when there is no such key or the call failed (recall then falls
    back to keywords). `model` is the model of the last key used (vectors of another model are redone)."""

    def __init__(self, router_fn: Callable[[], Any], embed: Callable[..., Any] = openai_embed):
        self.router_fn, self.embed = router_fn, embed
        self.model: str | None = None
        self.last_error: str | None = None

    def available(self) -> bool:
        r = self.router_fn()
        return bool(r is not None and any("embeddings" in e.categories and getattr(e, "enabled", True)
                                          for e in getattr(r, "entries", [])))

    def __call__(self, texts: list[str]) -> list[list[float]] | None:
        if not texts or not self.available():
            return None
        from .keys import KeysExhausted
        router = self.router_fn()
        out: list[list[float]] = []
        for i in range(0, len(texts), MAX_BATCH):
            chunk = texts[i:i + MAX_BATCH]
            try:
                lease = router.acquire("embeddings", prompt_tokens=sum(len(t) for t in chunk) // 3 + 8,
                                       label="memory")
            except KeysExhausted as e:
                self.last_error = str(e)[:200]
                return None
            if "embeddings" not in lease.entry.categories or not lease.base_url or not lease.model:
                lease.release()
                return None
            try:
                vecs, used = self.embed(lease.base_url, lease.model, lease.api_key, chunk)
            except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
                lease.fail(getattr(e, "code", None))
                self.last_error = f"{type(e).__name__}: {str(e)[:160]}"
                return None
            lease.commit(used or sum(len(t) for t in chunk) // 3, 0)
            self.model = lease.model
            out.extend(vecs)
        self.last_error = None
        return out
