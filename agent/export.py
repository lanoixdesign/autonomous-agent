"""Export one harness conversation + its audit trail, as JSON or Markdown (everything redacted)."""
from __future__ import annotations

import json
from typing import Any

from . import i18n
from .redact import redact

FORMATS = ("json", "md")


def bundle(task: dict, events: list[dict], audit: list[dict], usage: dict) -> dict:
    return redact({"format": "autonomous-agent/conversation-export", "version": 1,
                   "conversation": task, "usage": usage, "events": events, "audit": audit})


def _quote(text: Any) -> str:
    s = str(text if text is not None else "").rstrip()
    return "\n".join("> " + line if line else ">" for line in s.splitlines()) or ">"


def _inline(v: Any, n: int = 160) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    s = s.replace("\n", " ").replace("|", "\\|").replace("`", "'")
    return s if len(s) <= n else s[:n] + "…"


def _audit_line(a: dict, L) -> str:
    who = a.get("agent", "root")
    if a.get("event"):
        ev = a["event"]
        extra = {k: v for k, v in a.items() if k not in ("ts", "event", "agent", "depth", "task_id")}
        return f"| {a.get('ts', '')} | {who} | **{ev}** | | {_inline(extra)} |"
    cat = L("cat." + a["category"]) if a.get("category") else "-"
    dec = L("decision." + a["decision"]) if a.get("decision") else ""
    return (f"| {a.get('ts', '')} | {who} | `{a.get('tool', '?')}` ({cat}) | "
            f"{dec}{'' if a.get('ok', True) else ' ✗'} | {_inline(a.get('args', ''))} |")


def markdown(b: dict, lang: str = "en") -> str:
    """Markdown export; labels in English or French (tool names, ids and audit field values unchanged)."""
    def L(key: str, **kw: Any) -> str:
        return i18n.t(lang, key, **kw)

    def st(v: Any) -> str:
        return L("status." + str(v)) if ("status." + str(v)) in i18n.EN else str(v)
    t, u = b["conversation"], b["usage"]
    out = [f"# {L('export.title', id=t['id'])}", "",
           f"- **{L('export.firstMessage')}:** {_inline(t.get('task'), 300)}",
           f"- **{L('export.status')}:** {st(t.get('status'))} · **{L('export.turns')}:** {t.get('turns')} · "
           f"**{L('export.source')}:** {t.get('source', 'chat')}",
           f"- **{L('export.created')}:** {t.get('created')} · **{L('export.finished')}:** {t.get('finished') or '-'}", "",
           f"## {L('export.usage')}", "",
           f"| {L('export.agent')} | {L('export.parent')} | {L('export.steps')} | {L('export.toolCalls')} | "
           f"{L('export.tokens')} | {L('export.cost')} |", "|---|---|---|---|---|---|"]
    for a in u.get("agents", []):
        out.append(f"| {a['id']} | {a.get('parent') or '-'} | {a['steps']} | {a['tool_calls']} | {a['tokens']} | "
                   f"{a['cost']:.6f} |")
    tot = u.get("total", {})
    out += [f"| **{L('export.total')}** | | {tot.get('steps', 0)} | {tot.get('tool_calls', 0)} | {tot.get('tokens', 0)} | "
            f"{tot.get('cost', 0):.6f} |", "", f"## {L('export.transcript')}", ""]
    for e in b["events"]:
        k = e.get("kind")
        if k == "user":
            out += [f"### {L('export.you', turn=e.get('turn'), ts=e.get('ts'))}", "", _quote(e.get("text")), ""]
            for f in e.get("attachments") or []:
                out.append(f"- 📎 `{f.get('path')}` ({L('export.bytes', n=f.get('bytes'))})")
            out.append("")
        elif k == "message" and e.get("content"):
            out += [f"**{e.get('agent', 'root')}**{L('export.final') if e.get('final') else ''}:", "",
                    _quote(e.get("content")), ""]
        elif k == "approval" and e.get("status") != "pending":
            rule = L("export.rule", rule=e["rule"]) if e.get("rule") else ""
            out.append("- " + L("export.approval", tool=e.get("tool"), agent=e.get("agent"), status=st(e.get("status")),
                                rule=rule))
        elif k == "status" and e.get("status") not in ("queued", "running"):
            out += ["", L("export.statusLine", status=st(e.get("status"))), ""]
    out += ["", f"## {L('export.audit')}", "", L("export.auditCount", n=len(b["audit"])), "",
            f"| {L('export.time')} | {L('export.agent')} | {L('export.toolEvent')} | {L('export.decision')} | "
            f"{L('export.details')} |", "|---|---|---|---|---|"]
    out += [_audit_line(a, L) for a in b["audit"]]
    return "\n".join(out) + "\n"
