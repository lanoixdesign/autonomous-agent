"""Durable memory as plain files: memory/profile.md (stable facts) + memory/journal.jsonl (notes).

Recall is a simple keyword score (no embeddings, no network). `forget` removes matching
journal entries and profile lines; it is the only operation that rewrites memory files.
"""
from __future__ import annotations

import json
import re
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

    # ----- write -----
    def write(self, text: str, kind: str = "note", tags: list[str] | None = None) -> dict:
        text = redact(text.strip())
        if not text:
            raise ValueError("empty memory")
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
