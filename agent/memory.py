"""Durable memory as plain files: memory/profile.md (stable facts) + memory/journal.jsonl (notes).

Recall is a keyword score; with an embeddings key (v0.9) it is hybrid: meaning (cosine similarity of
embeddings kept in memory/vectors.sqlite3, see vectors.py) + keywords. `forget` removes matching journal
entries and profile lines; it is the only operation that rewrites memory files.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from pathlib import Path

from .redact import redact

WORD = re.compile(r"[\wÀ-ÿ]{2,}", re.UNICODE)


def _words(text: str) -> list[str]:
    return [w.lower() for w in WORD.findall(text)]


class Memory:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.profile = self.root / "profile.md"
        self.journal = self.root / "journal.jsonl"
        if not self.profile.exists():
            self.profile.write_text("# Profile\n\n", encoding="utf-8")
        self.journal.touch(exist_ok=True)
        self._lock = threading.RLock()   # harness: several agents may share one memory
        self.embedder = None             # vectors.RouterEmbedder (or any texts -> vectors callable), v0.9
        self._index = None
        self.last_mode = "keyword"

    @property
    def index(self):
        if self._index is None:
            from .vectors import VectorIndex
            self._index = VectorIndex(self.root / "vectors.sqlite3")
        return self._index

    def semantic_on(self) -> bool:
        e = self.embedder
        if e is None:
            return False
        avail = getattr(e, "available", None)
        try:
            return bool(avail()) if callable(avail) else True
        except Exception:  # noqa: BLE001
            return False

    def status(self) -> dict:
        on = self.semantic_on()
        return {"semantic": on, "vectors": self.index.count() if on or self._index is not None else 0,
                "model": getattr(self.embedder, "model", None) if on else None,
                "error": getattr(self.embedder, "last_error", None) if on else None}

    @staticmethod
    def _item_id(it: dict) -> str:
        if it.get("kind") == "profile" and it.get("id") in (None, "profile"):
            return "p:" + hashlib.sha1(it["text"].encode("utf-8")).hexdigest()[:12]
        return "j:" + str(it.get("id"))

    def _vectors(self, items: list[dict], limit_new: int = 64) -> dict[str, list[float]]:
        """Vectors of these items (cached in SQLite; at most `limit_new` new ones embedded per call)."""
        model = getattr(self.embedder, "model", None) or "default"
        out, missing = {}, []
        for it in items:
            iid = self._item_id(it)
            v = self.index.get(iid, it["text"], model)
            if v is not None:
                out[iid] = v
            elif len(missing) < limit_new:
                missing.append((iid, it["text"]))
        if missing:
            vecs = self.embedder([t for _, t in missing])
            if vecs:
                model = getattr(self.embedder, "model", None) or "default"
                for (iid, text), v in zip(missing, vecs):
                    self.index.put(iid, text, model, v)
                    out[iid] = v
        return out

    # ----- write -----
    def write(self, text: str, kind: str = "note", tags: list[str] | None = None) -> dict:
        text = redact(text.strip())
        if not text:
            raise ValueError("empty memory")
        with self._lock:
            entry = self._write(text, kind, tags)
        if self.semantic_on():                   # best effort: recall embeds what is missing anyway
            try:
                self._vectors([entry])
            except Exception:  # noqa: BLE001
                pass
        return entry

    def _write(self, text: str, kind: str, tags: list[str] | None) -> dict:
        if kind == "profile":
            with self.profile.open("a", encoding="utf-8") as f:
                f.write(f"- {text}\n")
            return {"kind": "profile", "text": text}
        entry = {"id": uuid.uuid4().hex[:8], "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                 "kind": kind, "tags": list(tags or []), "text": text}
        with self.journal.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    # ----- read -----
    def entries(self) -> list[dict]:
        out = []
        for line in self.journal.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def profile_lines(self) -> list[str]:
        return [ln[2:].strip() for ln in self.profile.read_text(encoding="utf-8").splitlines() if ln.startswith("- ")]

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        if query.strip() and self.semantic_on():
            try:
                hits = self._hybrid(query, limit)
                if hits is not None:
                    self.last_mode = "hybrid"
                    return hits
            except Exception:  # noqa: BLE001 - never lose recall because of the embeddings service
                pass
        self.last_mode = "keyword"
        return self._keyword(query, limit)

    def _hybrid(self, query: str, limit: int) -> list[dict] | None:
        """Meaning + keywords: 0.65 x cosine similarity + 0.35 x keyword score (normalised)."""
        from .vectors import cosine
        items = [{"id": "profile", "kind": "profile", "text": t, "tags": []} for t in self.profile_lines()]
        items += self.entries()
        if not items:
            return []
        qv = self.embedder([query])
        if not qv:
            return None
        vecs = self._vectors(items)
        if not vecs:
            return None
        self.index.delete_missing({self._item_id(it) for it in items})
        kw = {id(it): s for s, _, it in self._scored(query, items)}
        top = max(kw.values() or [0]) or 1
        out = []
        for idx, it in enumerate(items):
            cos = cosine(qv[0], vecs.get(self._item_id(it)) or [])
            k = kw.get(id(it), 0) / top
            score = 0.65 * cos + 0.35 * k
            if cos >= 0.2 or k > 0:
                out.append((score, idx, dict(it, semantic=round(cos, 3), keyword=round(k, 3))))
        out.sort(key=lambda x: (-x[0], -x[1]))
        return [dict(it, score=round(sc, 3), how="hybrid") for sc, _, it in out[:limit]]

    def _scored(self, query: str, items: list[dict]) -> list[tuple]:
        q = set(_words(query))
        out = []
        for idx, it in enumerate(items):
            words = _words(it["text"] + " " + " ".join(it.get("tags", [])))
            if q:
                score = sum(1 for w in words if w in q) + 2 * len(q & set(words))
                score += sum(0.5 for qw in q for w in set(words) if len(qw) >= 4 and qw != w and (w.startswith(qw) or qw.startswith(w)))
                if score > 0:
                    out.append((score, idx, it))
        return out

    def _keyword(self, query: str, limit: int = 5) -> list[dict]:
        q = set(_words(query))
        items = [{"id": "profile", "kind": "profile", "text": t, "tags": []} for t in self.profile_lines()]
        items += self.entries()
        scored = []
        for idx, it in enumerate(items):
            words = _words(it["text"] + " " + " ".join(it.get("tags", [])))
            if not q:
                score = 0.0
            else:
                score = sum(1 for w in words if w in q) + 2 * len(q & set(words))
                score += sum(0.5 for qw in q for w in set(words) if len(qw) >= 4 and qw != w and (w.startswith(qw) or qw.startswith(w)))
            if score > 0 or not q:
                scored.append((score, idx, it))
        scored.sort(key=lambda x: (-x[0], -x[1]))
        return [dict(it, score=round(s, 2)) for s, _, it in scored[:limit]]

    def context(self, max_chars: int = 1500) -> str:
        """Short memory snippet for the system prompt: profile + last notes."""
        parts = [f"- {t}" for t in self.profile_lines()]
        parts += [f"- [{e['ts'][:10]}] {e['text']}" for e in self.entries()[-5:]]
        return "\n".join(parts)[:max_chars]

    # ----- forget -----
    def forget(self, query: str) -> int:
        """Remove journal entries whose id equals `query` or whose text contains it (case-insensitive),
        and profile lines containing it. Returns the number of removed items."""
        ql = query.lower().strip()
        if not ql:
            return 0
        with self._lock:
            return self._forget(query, ql)

    def _forget(self, query: str, ql: str) -> int:
        kept, removed = [], 0
        for e in self.entries():
            if e.get("id") == query or ql in e.get("text", "").lower():
                removed += 1
            else:
                kept.append(e)
        self.journal.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in kept), encoding="utf-8")
        lines = self.profile.read_text(encoding="utf-8").splitlines(keepends=True)
        new = [ln for ln in lines if not (ln.startswith("- ") and ql in ln.lower())]
        removed += len(lines) - len(new)
        self.profile.write_text("".join(new), encoding="utf-8")
        return removed
