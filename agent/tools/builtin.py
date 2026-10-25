"""Memory and skill tools."""
from __future__ import annotations

import json

from . import Tool, ToolContext, ToolError, params, s


def _mem_write(ctx: ToolContext, a: dict) -> str:
    kind = a.get("kind") or "note"
    if kind not in ("note", "profile", "decision", "todo"):
        raise ToolError("kind must be note, profile, decision or todo")
    tags = a.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    e = ctx.memory.write(a["text"], kind=kind, tags=tags)
    return "saved: " + json.dumps(e, ensure_ascii=False)


def _mem_recall(ctx: ToolContext, a: dict) -> str:
    hits = ctx.memory.recall(a.get("query", ""), limit=int(a.get("limit") or 5))
    return "\n".join(f"[{h.get('id')}] ({h.get('kind')}, score {h['score']}) {h['text']}" for h in hits) or "nothing found"


def _mem_forget(ctx: ToolContext, a: dict) -> str:
    return f"forgot {ctx.memory.forget(a['query'])} item(s)"


def _skills_list(ctx: ToolContext, a: dict) -> str:
    return ctx.skills.index() or "no skills installed"


def _skill_load(ctx: ToolContext, a: dict) -> str:
    try:
        return ctx.skills.load(a["name"])
    except KeyError as e:
        raise ToolError(str(e))


TOOLS = [
    Tool("memory_write", "Save a durable note (kind: note|profile|decision|todo).", "write",
         params(["text"], text=s("what to remember"), kind=s("note|profile|decision|todo"),
                tags={"type": "array", "items": {"type": "string"}}), _mem_write),
    Tool("memory_recall", "Keyword search in durable memory.", "read",
         params([], query=s("keywords"), limit={"type": "integer"}), _mem_recall),
    Tool("memory_forget", "Delete memory items whose id or text matches.", "write",
         params(["query"], query=s("entry id or text fragment")), _mem_forget),
    Tool("list_skills", "List available skills (name: description).", "read", params([]), _skills_list),
    Tool("load_skill", "Load the full instructions of a skill by name before following it.", "read",
         params(["name"], name=s("skill name")), _skill_load),
]
