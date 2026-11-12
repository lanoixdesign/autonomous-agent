"""Export one harness conversation + its audit trail, as JSON or Markdown (everything redacted)."""
from __future__ import annotations

import json
from typing import Any

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


def _audit_line(a: dict) -> str:
    who = a.get("agent", "root")
    if a.get("event"):
        ev = a["event"]
        extra = {k: v for k, v in a.items() if k not in ("ts", "event", "agent", "depth", "task_id")}
        return f"| {a.get('ts', '')} | {who} | **{ev}** | | {_inline(extra)} |"
    return (f"| {a.get('ts', '')} | {who} | `{a.get('tool', '?')}` ({a.get('category', '-')}) | "
            f"{a.get('decision', '')}{'' if a.get('ok', True) else ' ✗'} | {_inline(a.get('args', ''))} |")


def markdown(b: dict) -> str:
    t, u = b["conversation"], b["usage"]
    out = [f"# Conversation {t['id']}", "",
           f"- **First message:** {_inline(t.get('task'), 300)}",
           f"- **Status:** {t.get('status')} · **turns:** {t.get('turns')} · **source:** {t.get('source', 'chat')}",
           f"- **Created:** {t.get('created')} · **finished:** {t.get('finished') or '-'}", "",
           "## Usage", "", "| agent | parent | steps | tool calls | tokens | cost |", "|---|---|---|---|---|---|"]
    for a in u.get("agents", []):
        out.append(f"| {a['id']} | {a.get('parent') or '-'} | {a['steps']} | {a['tool_calls']} | {a['tokens']} | "
                   f"{a['cost']:.6f} |")
    tot = u.get("total", {})
    out += [f"| **total** | | {tot.get('steps', 0)} | {tot.get('tool_calls', 0)} | {tot.get('tokens', 0)} | "
            f"{tot.get('cost', 0):.6f} |", "", "## Transcript", ""]
    for e in b["events"]:
        k = e.get("kind")
        if k == "user":
            out += [f"### You — turn {e.get('turn')} ({e.get('ts')})", "", _quote(e.get("text")), ""]
            for f in e.get("attachments") or []:
                out.append(f"- 📎 `{f.get('path')}` ({f.get('bytes')} bytes)")
            out.append("")
        elif k == "message" and e.get("content"):
            out += [f"**{e.get('agent', 'root')}**{' (final)' if e.get('final') else ''}:", "",
                    _quote(e.get("content")), ""]
        elif k == "approval" and e.get("status") != "pending":
            rule = f" (rule {e['rule']})" if e.get("rule") else ""
            out.append(f"- 🔐 approval `{e.get('tool')}` asked by {e.get('agent')}: **{e.get('status')}**{rule}")
        elif k == "status" and e.get("status") not in ("queued", "running"):
            out += ["", f"_status: {e.get('status')}_", ""]
    out += ["", "## Audit trail", "", f"{len(b['audit'])} entries from the append-only audit file "
            "(secrets redacted).", "", "| time | agent | tool / event | decision | details |", "|---|---|---|---|---|"]
    out += [_audit_line(a) for a in b["audit"]]
    return "\n".join(out) + "\n"
