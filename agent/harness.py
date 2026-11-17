"""Local harness: `python -m agent serve`. Runs agent tasks in background threads behind a small
JSON API (stdlib http.server) and a one-page UI, with an approval queue instead of terminal prompts.

API (JSON):
  POST /tasks                 {"task": "..."}            -> 201 {"id": ...}   (a task is a conversation)
  POST /tasks/{id}/messages   {"text": "..."}            -> continue the conversation (409 if busy)
      both accept "files": [{"name": ..., "content_b64": ...}] -> saved in <workspace>/uploads/<id>/
  GET  /config                upload limits
  GET  /keys                  API keys (masked) with used / remaining quota per limit, by category
  GET  /tasks                                            -> {"tasks": [...]}
  GET  /tasks/{id}            task + agent tree (root, root.1, ...) + status + result
  GET  /tasks/{id}/events?since=N                        -> {"events": [...], "next": M}  (polling)
  GET  /tasks/{id}/graph      live swarm graph of the current turn: agents, progress (steps / budget),
                              merges, files written;  GET /tasks/{id}/file?path=P  one of those files
  POST /tasks/{id}/cancel
  GET  /tasks/{id}/stream     Server-Sent Events (same events, pushed; ?access_token= if a token is set)
  GET  /tasks/{id}/export?format=json|md[&lang=fr]       conversation + its audit trail (redacted)
  GET  /approvals[?all=1]     pending (or all) approval requests, each with the requesting agent id
  POST /approvals/{id}        {"decision": "approve" | "deny", "remember": "conversation" | "session"}
  GET  /rules                 remembered approval rules;  POST /rules/{id}/revoke
  POST /stop-all              emergency stop: cancel every task, deny every pending approval
  GET  /usage                 tokens / cost / steps per conversation and per agent + key quotas
  GET  /schedules             POST /schedules {"prompt", "every_minutes" | "daily_at": "HH:MM"}
  POST /schedules/{id}        {"enabled": bool};  POST /schedules/{id}/run;  POST /schedules/{id}/delete
  GET  /health[?check=1]      status, keys (masked), backend reachability (network only with check=1)
  GET  /[?lang=fr|en]         chat page (approvals pop up as cards); pages are English/French
  GET  /dashboard             compact dashboard page
  GET  /connect[?pair=CODE]   sign-in page (token or one-time pairing code from a QR code); pairing QR
  POST /auth/login            {"token": ...} or {"pair": ...} -> session cookie (rate limited)
  POST /auth/logout;  GET /auth/status;  POST /auth/pair (new one-time code + QR, signed in only)
  POST /auth/revoke-all       sign every device out
  GET  /settings (browser)    Settings page;  GET /welcome  first-run wizard
  GET  /app/status            first run?, demo mode, restart needed, may this device change settings, CSRF token
  GET  /app/settings          every setting (no secret);  POST /app/settings {section: value, ...}
  GET  /app/providers         API keys entered in the UI, MASKED, with usage;  POST /app/providers (add)
  POST /app/providers/{id}    edit ("key" empty/absent = keep);  POST /app/providers/{id}/delete | /test
  POST /app/providers/test    test a key typed in the form (not saved);  POST /app/providers/order {"ids"}
  POST /app/providers/bulk    {"text"}: many keys, one per line ("label: key"), tested at once, good ones saved
  POST /app/providers/propose proposed task types per key;  POST /app/providers/tasks {"assign": {id: [..]}}
  GET  /keys/rate             tokens / requests left per minute, per key (masked; provider headers or estimate)
  GET  /app/pool              live key pool: per key (masked) the agents using it, in-flight requests, usage
  POST /app/setup             first-run wizard {"lang", "demo", "done"};  POST /app/remote/token (new token)
  POST /app/restart, /app/quit   stop the server cleanly (restart: the launcher starts it again)
      /app/* changes: only from this computer, unless AGENT_REMOTE_SETTINGS=1 (then sign-in + X-CSRF-Token)
  GET  /manifest.webmanifest, /sw.js, /icon-*.png   installable web app (PWA); the service worker caches
                              the page shell only, never API answers or approvals

At most `max_tasks` turns run at once (default 4); the others wait in status "queued".

Persistence (optional `store`): conversations, events, schedules and conversation-scoped rules are kept
in SQLite and restored at start; a turn that was running when the process stopped becomes "interrupted".

Approvals: each `ask` decision becomes a pending approval; the agent thread waits until someone
approves/denies it, the task is cancelled, or `approval_timeout` seconds pass. No answer = deny.

Security: binds 127.0.0.1 by default. If AGENT_HARNESS_TOKEN is set, every API call needs
`Authorization: Bearer <token>` or a session cookie obtained with that token / a pairing code. Remote
mode (`--remote`, see agent/remote.py) makes a strong token mandatory for everything that does not come
directly from this computer; a non-local bind address without a token is refused. POSTs must be `application/json` and same-origin, and the Host header
is checked when bound to localhost (protects against other web pages and DNS rebinding). This is NOT
an authenticated multi-user server: do not expose it to a network you do not trust.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .audit import AuditLog, _short
from .harness_page import PAGE
from .harness_chat import CHAT_PAGE
from .harness_connect import CONNECT_PAGE
from .harness_settings import SETTINGS_PAGE, WELCOME_PAGE
from .harness_help import HELP_PAGE
from .harness_dev import DEV_PAGE

FILE_DOWNLOAD_MAX = 200 * 1024 * 1024   # "My files" downloads
FILES_LIST_MAX = 500
from . import pwa, qr, remote
from .redact import MASK as MASK_TEXT, redact
from . import __version__, devmode, export, i18n, schedule, uploads, mcp
from .idc import IDC, IDCConfig
from .keys import role_task
from . import sandbox as sandbox_mod
from .theme import CALM_CSS, THEME_HEAD

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
_I18N_DATA = json.dumps(i18n.ui_strings(), ensure_ascii=False).replace("</", "<\\/")


def _lang_arg(data: dict) -> str | None:
    v = data.get("lang")
    return v if isinstance(v, str) and v[:2].lower() in i18n.LANGS else None


def render_page(page: str, lang: str | None = None, default_lang: str | None = None, theme: str | None = None) -> bytes:
    """Insert the EN/FR dictionaries; `?lang=` also sets <html lang> (the page then remembers it).
    `default_lang` (Settings page choice) is used by a browser that has no saved choice yet."""
    out = page.replace("/*I18N_DATA*/{}", _I18N_DATA)
    if default_lang in i18n.LANGS:
        out = out.replace("const I18N_DEFAULT = null;", f'const I18N_DEFAULT = "{default_lang}";', 1)
    # day / night theme: applied in <head> before the first paint (no flash); `theme` = Settings choice
    th = THEME_HEAD.replace('"__THEME_DEFAULT__"', json.dumps(theme if theme in ("auto", "light", "dark") else "auto"))
    out = out.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n' + pwa.HEAD + "\n" + th, 1)
    out = out.replace("width=device-width, initial-scale=1", "width=device-width, initial-scale=1, viewport-fit=cover", 1)
    out = out.replace("</script></body></html>", pwa.REGISTER_JS + "\n</script></body></html>", 1)
    # v0.9.1: the calm layer goes last in <head>, so it wins over each page's own colours and effects
    out = out.replace("</head>", "<style>" + CALM_CSS + "</style></head>", 1)
    if lang:
        out = out.replace('<html lang="en">', f'<html lang="{i18n.normalize(lang)}">', 1)
    return out.encode("utf-8")
MAX_BODY = 1_000_000
MAX_TASK_CHARS = 20_000
TERMINAL = ("done", "stopped", "cancelled", "error", "interrupted")
# masked key name / value of each swarm agent, renamed when saved so redact() keeps them (see on_progress)
POOL_OUT = {"key": "pool", "key_mask": "pool_mask", "key_task": "pool_task", "key_match": "pool_match", "keys": "pools"}
POOL_IN = {v: k for k, v in POOL_OUT.items()}


def _pool_fields(a: dict, names: dict) -> dict:
    # history saved before 0.8.2 has "***REDACTED***" there: drop it (the graph then shows no key)
    return {names.get(k, k): v for k, v in a.items()
            if not (names is POOL_IN and (k in POOL_OUT or k in POOL_IN) and v == MASK_TEXT)}


MAX_EARLIER = 24                        # helpers of earlier turns kept in the swarm graph
NEVER_REMEMBER = ("send", "spend")      # these are asked every single time, whatever the rules say
RULE_SCOPES = ("conversation", "session")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


# ---------------------------------------------------------------------------- approvals
class Approval:
    def __init__(self, id: str, task_id: str, agent: str, tool: str, category: str, args: Any, reason: str):
        self.id, self.task_id, self.agent, self.tool, self.category = id, task_id, agent, tool, category
        self.args, self.reason = _short(redact(args), 400), reason   # shown in the UI: redacted, short
        self.created, self.decided = _now(), None
        self.status = "pending"   # pending | approved | denied | expired | cancelled
        self.event = threading.Event()

    def as_dict(self) -> dict:
        return {"id": self.id, "task": self.task_id, "agent": self.agent, "tool": self.tool,
                "category": self.category, "args": self.args, "reason": self.reason,
                "status": self.status, "created": self.created, "decided": self.decided,
                "rememberable": self.category not in NEVER_REMEMBER}


class ApprovalQueue:
    def __init__(self, timeout: float = 300.0):
        self.timeout = timeout
        self._lock = threading.Lock()
        self._items: dict[str, Approval] = {}

    def request(self, task_id: str, agent: str, tool: str, category: str, args: Any, reason: str,
                cancel: threading.Event | None = None,
                notify: Callable[[Approval], None] | None = None) -> bool:
        """Block until approved / denied / cancelled / timed out. Returns True only if approved."""
        ap = Approval(uuid.uuid4().hex[:10], task_id, agent, tool, category, args, reason)
        with self._lock:
            self._items[ap.id] = ap
        if notify:
            notify(ap)
        deadline = time.monotonic() + self.timeout
        while not ap.event.is_set():
            left = deadline - time.monotonic()
            if left <= 0 or (cancel is not None and cancel.is_set()):
                break
            ap.event.wait(min(0.1, left))
        with self._lock:
            if ap.status == "pending":   # nobody answered: timeout (or cancel) counts as deny
                ap.status = "cancelled" if cancel is not None and cancel.is_set() else "expired"
                ap.decided = _now()
        if notify:
            notify(ap)
        return ap.status == "approved"

    def get(self, approval_id: str) -> Approval | None:
        with self._lock:
            return self._items.get(approval_id)

    def decide(self, approval_id: str, approve: bool) -> Approval:
        with self._lock:
            ap = self._items.get(approval_id)
            if ap is None:
                raise KeyError(approval_id)
            if ap.status != "pending":
                raise ValueError(f"approval already {ap.status}")
            ap.status = "approved" if approve else "denied"
            ap.decided = _now()
        ap.event.set()
        return ap

    def deny_all(self) -> list[Approval]:
        """Emergency stop: deny every pending approval at once."""
        with self._lock:
            pending = [a for a in self._items.values() if a.status == "pending"]
            for a in pending:
                a.status, a.decided = "denied", _now()
        for a in pending:
            a.event.set()
        return pending

    def list(self, pending_only: bool = True) -> list[dict]:
        with self._lock:
            return [a.as_dict() for a in self._items.values() if a.status == "pending" or not pending_only]

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for a in self._items.values() if a.status == "pending")


class HarnessConfirm:
    """`confirm` callback for agents run by the harness; `with_agent` receives the asking agent id.
    `concurrent = True`: several agents may wait for approval at once (parallel sub-agents).
    A remembered rule ("always allow this tool here") answers without asking — never for send/spend."""

    concurrent = True

    def __init__(self, queue: ApprovalQueue, task: "Task", harness: "Harness | None" = None):
        self.queue, self.task, self.harness = queue, task, harness

    def __call__(self, tool: str, category: str, args: dict, reason: str) -> bool:
        return self.with_agent("root", tool, category, args, reason)

    def with_agent(self, agent: str, tool: str, category: str, args: dict, reason: str) -> bool:
        if self.task.cancel.is_set():
            return False
        rule = self.harness.match_rule(self.task.id, tool, category) if self.harness is not None else None
        if rule is not None:
            self.harness.rule_used(rule, self.task, agent, tool, category)
            return True

        def notify(ap: Approval) -> None:
            self.task.add_event("approval", agent=ap.agent, approval=ap.id, tool=ap.tool, status=ap.status)
        return self.queue.request(self.task.id, agent, tool, category, args, reason, self.task.cancel, notify)


# ---------------------------------------------------------------------------- tasks
USAGE_FIELDS = ("steps", "tool_calls", "tokens", "cost")


def _zero() -> dict:
    return {"steps": 0, "tool_calls": 0, "tokens": 0, "cost": 0.0}


def _add(into: dict, src: dict) -> None:
    for f in USAGE_FIELDS:
        v = src.get(f) or 0
        into[f] = into.get(f, 0) + (v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0)
    into["cost"] = round(into.get("cost", 0.0), 8)


class Task:
    def __init__(self, text: str, store: Any = None, source: str = "chat"):
        self.id = uuid.uuid4().hex[:10]
        self.text = text
        self.source = source            # "chat" | "schedule:<id>"
        self.status = "queued"
        self.created, self.finished = _now(), None
        self.result: str | None = None
        self.stop_reason: str | None = None
        self.usage: dict = {}           # last turn (steps, tool_calls, tokens, cost)
        self.total: dict = _zero()      # whole conversation
        self.agent_usage: dict[str, dict] = {}   # agent id -> {parent, steps, tool_calls, tokens, cost} (inclusive)
        self.cancel = threading.Event()
        self.agents: dict[str, dict] = {"root": {"id": "root", "parent": None, "depth": 0, "task": text,
                                                 "status": "queued", "answer": None}}
        self.events: list[dict] = []
        self.turns = 0
        self.agent: Any = None          # created on the first turn, kept for the conversation
        self.history: list[dict] | None = None   # restored messages (after a restart), given to the new agent
        self.idc = False                # IDC mode for this conversation (set at creation, can be toggled)
        self.idc_ctrl: Any = None       # idc.IDC controller, kept while the conversation lives
        self.idc_saved: list[dict] = []  # commitments restored from the store (after a restart)
        self.dev: str | None = None     # developer mode: project name (projects/<name>/), None otherwise
        self.ui_lang: str | None = None  # language of the page the user wrote from (when the text is unclear)
        self.last_text: str | None = None  # this turn's message as the user wrote it
        self.pinned = False             # v0.9.5: kept at the top of the conversation list
        self.store = store
        self._lock = threading.Condition(threading.RLock())   # also wakes SSE streams on new events

    # -- persistence
    def record(self) -> dict:
        with self._lock:
            history = self.agent.messages if self.agent is not None else self.history
            return redact({"id": self.id, "task": self.text, "source": self.source, "status": self.status,
                           "created": self.created, "finished": self.finished, "result": self.result,
                           "stop_reason": self.stop_reason, "usage": self.usage, "total": self.total,
                           "agent_usage": self.agent_usage,
                           "agents": [_pool_fields(a, POOL_OUT) for a in self.agents.values()],
                           "turns": self.turns, "history": history, "idc": self.idc, "dev": self.dev,
                           "pinned": self.pinned, "idc_commitments": self.commitments()})

    def commitments(self) -> list[dict]:
        return self.idc_ctrl.commitments if self.idc_ctrl is not None else list(self.idc_saved)

    def save(self) -> None:
        if self.store is not None:
            self.store.put("tasks", self.id, self.record())

    @classmethod
    def restore(cls, rec: dict, events: list[dict], store: Any) -> "Task":
        t = cls(rec.get("task") or "", store, rec.get("source") or "chat")
        t.id = rec["id"]
        for f in ("status", "created", "finished", "result", "stop_reason", "usage", "turns", "history"):
            if rec.get(f) is not None:
                setattr(t, f, rec[f])
        t.total = {**_zero(), **(rec.get("total") or {})}
        t.agent_usage = rec.get("agent_usage") or {}
        t.idc = bool(rec.get("idc"))
        t.dev = rec.get("dev") if isinstance(rec.get("dev"), str) else None
        t.pinned = rec.get("pinned") is True
        t.idc_saved = [c for c in rec.get("idc_commitments") or [] if isinstance(c, dict)]
        t.agents = {a["id"]: _pool_fields(a, POOL_IN) for a in rec.get("agents") or [] if isinstance(a, dict)} or t.agents
        t.events = events
        if t.status not in TERMINAL:     # the server stopped in the middle of this turn
            t.status, t.stop_reason = "interrupted", "interrupted"
            t.result = "Interrupted: the harness stopped during this turn. Send a message to continue."
            t.finished = _now()
            for a in t.agents.values():
                if a.get("status") not in TERMINAL + ("done",):
                    a["status"] = "interrupted"
            t.add_event("status", status="interrupted")
            t.save()
        return t

    def new_turn(self, text: str, attachments: list[dict] | None = None) -> None:
        with self._lock:
            earlier = self._earlier_agents()
            self.turns += 1
            self.status = "queued"
            self.finished = None
            self.result = self.stop_reason = None
            self.agents = {"root": {"id": "root", "parent": None, "depth": 0, "task": text,
                                    "status": "queued", "answer": None}, **earlier}
        self.cancel.clear()
        self.add_event("user", text=text, turn=self.turns, attachments=attachments or [])
        self.add_event("status", status="queued")
        self.save()

    def _earlier_agents(self) -> dict[str, dict]:
        """Helpers of the previous turns, kept in the graph after "Continue" (ids prefixed with their turn:
        t1:root.2) so the new turn's helpers (root.1, ...) do not replace them. Newest MAX_EARLIER only."""
        n = self.turns
        out: dict[str, dict] = {}
        for aid, a in self.agents.items():
            if aid == "root":
                continue
            if a.get("earlier"):
                out[aid] = a
                continue
            b = dict(a, id=f"t{n}:{aid}", earlier=True, turn=n)
            par = a.get("parent")
            b["parent"] = par if par in (None, "root") else f"t{n}:{par}"
            if b.get("status") in (None, "queued", "running", "cancelling"):
                b["status"] = "interrupted"
            out[b["id"]] = b
        return dict(list(out.items())[-MAX_EARLIER:])

    def add_event(self, kind: str, **data: Any) -> None:
        with self._lock:
            ev = {"seq": len(self.events), "ts": _now(), "kind": kind, **data}
            self.events.append(ev)
            if self.store is not None:
                self.store.add_event(self.id, ev["seq"], redact(ev))
            self._lock.notify_all()

    def on_audit(self, entry: dict) -> None:
        self.add_event("audit", **{k: v for k, v in entry.items() if k != "task_id"})
        ev = entry.get("event")
        with self._lock:
            if ev == "spawn":
                self.agents[entry["child"]] = {"id": entry["child"], "parent": entry.get("agent"),
                                               "depth": entry.get("child_depth"),
                                               "task": (str(entry.get("task") or "").split("\n\n")[0]
                                                        if entry.get("handoff") else entry.get("task")),
                                               "status": "running", "answer": None, "steps": 0,
                                               "max_steps": (entry.get("budget") or {}).get("max_steps"),
                                               "isolated": bool(entry.get("isolated")),
                                               "handoff": bool(entry.get("handoff"))}
            elif ev == "critic" and entry.get("critic"):    # self-evaluation: one node per review
                lang = entry.get("lang") or getattr(self, "ui_lang", None) or "en"
                self.agents[entry["critic"]] = {
                    "id": entry["critic"], "parent": entry.get("agent") or "root", "depth": 1,
                    "task": i18n.t(lang, "critic.task", n=entry.get("round") or 1),
                    "status": "done" if entry.get("ok") else "revise", "steps": 1, "max_steps": 1,
                    "answer": "; ".join(entry.get("issues") or []) or None, "critic": True,
                    "score": entry.get("score")}
            elif ev == "child_done" and entry.get("agent") in self.agents:
                a = self.agents[entry["agent"]]
                a["status"] = "done" if entry.get("stop_reason") == "final" else entry.get("stop_reason")
                a["answer"] = entry.get("result")
                if entry.get("steps") is not None:
                    a["steps"] = entry["steps"]
                u = self.agent_usage.setdefault(entry["agent"], {"parent": entry.get("parent"), **_zero()})
                _add(u, entry)

    def on_progress(self, agent: str, steps: Any, max_steps: Any, key: dict | None = None) -> None:
        """One model step done by `agent` (live progress for the swarm graph). `key`: the pool key that
        served it (name and MASKED value only, never the secret) and the task type it was picked for."""
        key = {k: v for k, v in (key or {}).items() if k in ("key", "key_mask", "key_task", "key_match")}
        with self._lock:
            a = self.agents.get(agent)
            if a is not None:
                a["steps"], a["max_steps"] = steps, max_steps
                if key.get("key"):
                    keys = a.setdefault("keys", [])
                    if key["key"] not in keys:
                        keys.append(key["key"])          # more than one: the agent failed over
                    a.update(key)
        # stored as pool / pool_mask: field names with "key" are blanked by redact() when saved, and the
        # history must still show the MASKED key after a restart (the secret itself is never here)
        self.add_event("progress", agent=agent, steps=steps, max_steps=max_steps,
                       **({"pool": key["key"], "pool_mask": key.get("key_mask")} if key.get("key") else {}))

    def graph(self) -> dict:
        """The current turn's agent tree with live progress, plus what was merged / written (swarm graph)."""
        with self._lock:
            agents = [dict(a) for a in self.agents.values()]
            start = max((i for i, e in enumerate(self.events) if e.get("kind") == "user"), default=0)
            evs = [e for e in self.events[start:] if e.get("kind") == "audit"]
            status, turn = self.status, self.turns
        out = []
        for a in agents:
            st, mx = a.get("steps") or 0, a.get("max_steps") or 0
            done = a.get("status") not in (None, "queued", "running", "cancelling")
            prog = 1.0 if done else (min(1.0, st / mx) if mx else 0.0)
            out.append({"id": a["id"], "parent": a.get("parent"), "depth": a.get("depth") or 0,
                        "task": ((a.get("task") or "").split("\n\n")[0] if a.get("handoff") else (a.get("task") or ""))[:300],
                        "status": a.get("status"), "steps": st,
                        "max_steps": mx or None, "progress": round(prog, 3),
                        "isolated": bool(a.get("isolated")), "answer": (a.get("answer") or "")[:500] or None,
                        "role": a.get("role") or role_task(a.get("task") if a["id"] != "root" else ""),
                        "key": a.get("key"), "key_mask": a.get("key_mask"), "key_task": a.get("key_task"),
                        "key_match": bool(a.get("key_match")), "keys": list(a.get("keys") or []),
                        "earlier": bool(a.get("earlier")), "turn": a.get("turn"),
                        "handoff": bool(a.get("handoff")), "critic": bool(a.get("critic")),
                        "score": a.get("score")})
        merges = [{"agent": e.get("agent"), "children": e.get("children") or [],
                   "applied": e.get("applied") or [], "conflicts": e.get("conflicts") or [],
                   "skipped": e.get("skipped")} for e in evs if e.get("event") == "merge"]
        files: list[str] = []
        for e in evs:
            if e.get("tool") in ("write_file", "edit_file") and e.get("ok") and isinstance(e.get("args"), dict):
                p = e["args"].get("path")
                if p and p not in files:
                    files.append(p)
        for m in merges:
            for a in m["applied"]:
                if a.get("path") and a["path"] not in files:
                    files.append(a["path"])
        kids = [a for a in out if a["id"] != "root"]
        now = [a for a in kids if not a["earlier"]]          # this turn's helpers decide "finished and merged"
        busy = ("running", "queued", "cancelling")
        done = (all(a["status"] not in busy for a in now) if now else status in TERMINAL)
        return {"task": self.id, "turn": turn, "status": status, "agents": out, "merges": merges, "files": files,
                "children": len(kids), "children_now": len(now),
                "failed": sum(1 for a in kids if a["status"] not in busy + ("done", "revise")),
                "children_done": bool(kids) and done}

    def finish_turn(self, res: Any) -> None:
        with self._lock:
            self.usage = {"steps": res.steps, "tool_calls": res.tool_calls, "tokens": res.tokens,
                          "cost": getattr(res, "cost", 0.0)}
            _add(self.total, self.usage)
            _add(self.agent_usage.setdefault("root", {"parent": None, **_zero()}), self.usage)

    def usage_report(self) -> dict:
        """Per agent: inclusive counters (an agent's numbers include its sub-agents) and `own` ones."""
        with self._lock:
            agents = {k: dict(v) for k, v in self.agent_usage.items()}
            total = dict(self.total)
        out = []
        for aid, u in agents.items():
            own = {f: u.get(f, 0) for f in USAGE_FIELDS}
            for cid, c in agents.items():
                if c.get("parent") == aid:
                    for f in USAGE_FIELDS:
                        own[f] -= c.get(f, 0)
            own["cost"] = round(own["cost"], 8)
            out.append({"id": aid, "parent": u.get("parent"), **{f: u.get(f, 0) for f in USAGE_FIELDS},
                        "own": own})
        out.sort(key=lambda a: [int(x) if x.isdigit() else -1 for x in a["id"].split(".")])
        return {"total": total, "agents": out}

    def set_status(self, status: str) -> None:
        with self._lock:
            self.status = status
            self.agents["root"]["status"] = status
            if status in TERMINAL:
                self.finished = _now()
        self.save()

    def snapshot(self, full: bool = True) -> dict:
        with self._lock:
            d = {"id": self.id, "task": self.text, "status": self.status, "created": self.created,
                 "finished": self.finished, "stop_reason": self.stop_reason, "result": self.result,
                 "turns": self.turns, "source": self.source}
            d["idc"] = self.idc
            d["dev"] = self.dev
            d["pinned"] = self.pinned
            d["folder"] = conv_folder_rel(self.id, self.dev)
            if full:
                d["idc_state"] = ({**self.idc_ctrl.snapshot(), "list": self.idc_ctrl.commitments}
                                  if self.idc_ctrl is not None else {"list": list(self.idc_saved)})
                d["usage"] = dict(self.usage)
                d["total"] = dict(self.total)
                d["agents"] = [dict(a) for a in self.agents.values()]
                d["events"] = len(self.events)
            return d

    def events_since(self, since: int) -> tuple[list[dict], int]:
        with self._lock:
            return [dict(e) for e in self.events[max(since, 0):]], len(self.events)

    def wait_events(self, since: int, timeout: float) -> tuple[list[dict], int]:
        """Like events_since, but waits up to `timeout` seconds for something new (SSE)."""
        with self._lock:
            if len(self.events) <= since:
                self._lock.wait(timeout)
            return [dict(e) for e in self.events[max(since, 0):]], len(self.events)


class TaskAudit(AuditLog):
    """Same append-only file as the CLI; every entry is tagged with the task id and fed to the task."""

    def __init__(self, path: str | Path, task: Task):
        super().__init__(path)
        self.task = task

    def record(self, **entry: Any) -> dict:
        safe = super().record(task_id=self.task.id, **entry)
        self.task.on_audit(safe)
        return safe


# Factory signature: (task, audit, confirm, cancel, on_event) -> Agent
AgentFactory = Callable[[Task, AuditLog, Any, threading.Event, Callable[[str, dict], None]], Any]


class Busy(Exception):
    pass


def conv_folder_rel(task_id: str, dev: str | None) -> str:
    """v0.9.5: a conversation's folder in the work folder: its developer project, else conversations/<id>/."""
    return f"projects/{dev}" if dev else f"conversations/{task_id}"


def open_in_file_manager(path: Path) -> bool:
    """Show a folder in Finder / Explorer / the Linux file manager. No shell, the path is one argument."""
    import subprocess
    import sys as _sys
    if os.environ.get("AGENT_NO_OPEN") == "1":
        return False
    if _sys.platform == "darwin":
        cmd = ["open", "--", str(path)]
    elif _sys.platform == "win32":
        cmd = ["explorer", str(path)]
    else:
        cmd = ["xdg-open", str(path)]
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True)
        return True
    except OSError:
        return False


class ConvError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


class Harness:
    def __init__(self, agent_factory: AgentFactory, audit_path: str | Path, approval_timeout: float = 300.0,
                 max_tasks: int = 4, workspace: str | Path | None = None,
                 max_upload_mb: float = 20, max_message_mb: float = 50, key_router: Any = None,
                 store: Any = None, backend: dict | None = None, clock: Callable[[], float] = time.time,
                 scheduler_tick: float | None = 1.0, idc_config: IDCConfig | None = None, lang: str = "en"):
        self.factory = agent_factory
        self.csrf_secret = os.urandom(32)      # v0.9.5: conversation actions (pin / folder / delete)
        self.folder_opener: Callable[[Path], bool] = open_in_file_manager
        self.idc_config = idc_config or IDCConfig()   # parameters; .enabled = default for new conversations
        self.lang = i18n.normalize(lang)
        self.key_router = key_router   # keys.KeyRouter or None (.env single-key mode)
        self.workspace = Path(workspace) if workspace is not None else None   # None: uploads disabled
        self.upload_limits = uploads.Limits(int(max_upload_mb * 1024 * 1024),
                                            int(max(max_message_mb, max_upload_mb) * 1024 * 1024))
        # JSON body cap: base64 (4/3) of the per-message limit + room for the text
        self.max_body = max(MAX_BODY, self.upload_limits.max_message_bytes * 4 // 3 + MAX_BODY)
        self.audit_path = Path(audit_path)
        self.approvals = ApprovalQueue(approval_timeout)
        self.max_tasks = max(1, int(max_tasks))
        self._slots = threading.BoundedSemaphore(self.max_tasks)   # concurrent running turns
        self._tasks: dict[str, Task] = {}
        self._lock = threading.RLock()
        self.store = store                  # store.Store or None (in memory only)
        self.backend = backend or {}        # {"provider", "model", "base_url"} for /health (single-key mode)
        self.clock = clock
        self.started = clock()
        self.stopping = threading.Event()
        self.rules: dict[str, dict] = {}
        self.schedules: dict[str, dict] = {}
        self.mcp = mcp.MCPRegistry(self.audit_path.parent, None, None)  # simple registry; secrets later
        self.settings: dict[str, Any] = {"idc": bool(self.idc_config.enabled), "critic": False, "critic_rounds": 2}
        self.public_url: str | None = None   # remote mode: the URL a phone should open (tunnel, LAN...)
        self.control: Any = None             # userconfig.AppControl: Settings page, keys from the UI, restart / quit
        self.deny_paths: list[Path] = []     # private app data (state dir), never reachable from the sandbox
        self._projects: Any = None
        self.memory: Any = None              # shared durable memory (status of semantic recall on /health)
        self._restore()
        self._sched_thread = None
        if scheduler_tick:
            self._sched_thread = threading.Thread(target=self._scheduler_loop, args=(scheduler_tick,),
                                                  name="harness-scheduler", daemon=True)
            self._sched_thread.start()

    # -- persistence
    def _restore(self) -> None:
        if self.store is None:
            return
        for rec in self.store.all("tasks"):
            t = Task.restore(rec, self.store.events(rec["id"]), self.store)
            self._tasks[t.id] = t
        for r in self.store.all("rules"):
            if r.get("scope") == "session":     # session rules end with the process that created them
                self.store.delete("rules", r["id"])
            elif r.get("task_id") in self._tasks:
                self.rules[r["id"]] = r
        for s in self.store.all("schedules"):
            self.schedules[s["id"]] = s
        for s in self.store.all("settings"):
            if s.get("id") == "global" and isinstance(s.get("idc"), bool):
                self.settings["idc"] = s["idc"]
            if s.get("id") == "global" and isinstance(s.get("critic"), bool):
                self.settings["critic"] = s["critic"]
            if s.get("id") == "global" and isinstance(s.get("critic_rounds"), int):
                self.settings["critic_rounds"] = max(1, min(3, s["critic_rounds"]))

    # -- settings (global) and IDC per conversation
    def get_settings(self) -> dict:
        with self._lock:
            return {**self.settings, "idc_config": self.idc_config.as_dict()}

    def update_settings(self, data: dict) -> dict:
        if "critic" in data or "critic_rounds" in data:
            c, r = data.get("critic", self.settings["critic"]), data.get("critic_rounds", self.settings["critic_rounds"])
            if not isinstance(c, bool):
                raise ValueError("'critic' must be true or false")
            if isinstance(r, bool) or not isinstance(r, int) or not 1 <= r <= 3:
                raise ValueError("'critic_rounds' must be 1, 2 or 3")
            with self._lock:
                self.settings["critic"], self.settings["critic_rounds"] = c, r
                if self.store is not None:
                    self.store.put("settings", "global", {"id": "global", **self.settings})
        if "idc" in data:
            if not isinstance(data["idc"], bool):
                raise ValueError("'idc' must be true or false")
            with self._lock:
                self.settings["idc"] = data["idc"]
                if self.store is not None:
                    self.store.put("settings", "global", {"id": "global", **self.settings})
        return self.get_settings()

    def set_task_idc(self, task_id: str, enabled: bool) -> "Task":
        task = self.get(task_id)
        if task is None:
            raise KeyError(task_id)
        with task._lock:
            if task.status not in TERMINAL:
                raise Busy(f"task is {task.status}: change IDC between messages")
            changed = task.idc != enabled
            task.idc = enabled
        if changed:
            task.add_event("idc_toggle", enabled=enabled)
            self._audit(task, event="idc_toggle", agent="root", depth=0, enabled=enabled)
            task.save()
        return task

    def _sync_idc(self, task: "Task") -> None:
        """Give the conversation's agent its IDC controller (or take it away) before a turn."""
        agent = task.agent
        if agent is None or not hasattr(agent, "set_idc"):
            return
        if task.idc:
            if task.idc_ctrl is None:
                task.idc_ctrl = IDC(self.idc_config, lang=self.lang)
                task.idc_ctrl.restore(task.idc_saved)
            if agent.idc is not task.idc_ctrl:
                agent.set_idc(task.idc_ctrl)
        elif agent.idc is not None:
            agent.set_idc(None)
    def _sync_dev(self, task: "Task") -> None:
        """Developer-mode rules (and the current sandbox state) in the agent's system prompt before a turn."""
        agent = task.agent
        if agent is None or not hasattr(agent, "refresh_system"):
            return
        ui = task.ui_lang or (self.control.cfg.get("lang") if self.control is not None else None) or self.lang
        agent.ui_lang = ui
        agent.lang_hint = i18n.detect_lang(task.last_text) if task.last_text else None
        lang = agent.lang_hint or getattr(agent, "lang", None) or ui
        extra = ""
        if task.dev:
            try:
                kind = devmode.Projects.kind_of(self.projects().path(task.dev))
            except devmode.DevError:
                kind = None
            extra = devmode.rules(task.dev, kind, lang)
        elif self.workspace is not None:     # v0.9.5: one folder per conversation, opened from its ⋯ menu
            extra = (f"Files you create for this conversation go in conversations/{task.id}/ (create it) unless the "
                     "user names another place. Uploaded files stay where they are.")
        agent.extra_rules = extra
        agent.child_rules = devmode.child_rules(task.dev, lang) if task.dev else ""
        ctx = getattr(agent, "ctx", None)
        if ctx is not None and hasattr(ctx, "write_prefix"):
            prefix = f"projects/{task.dev}/" if task.dev else None
            if ctx.write_prefix != prefix:
                agent.ctx = dataclasses.replace(ctx, write_prefix=prefix)
        with self._lock:
            agent.critic_rounds = int(self.settings["critic_rounds"]) if self.settings.get("critic") else 0
        agent.refresh_system()

    def _audit(self, task: Task | None, **entry: Any) -> dict:
        return (TaskAudit(self.audit_path, task) if task is not None else AuditLog(self.audit_path)).record(**entry)

    def _decode(self, files: Any) -> list[tuple[str, bytes]]:
        decoded = uploads.decode(files, self.upload_limits)
        if decoded and self.workspace is None:
            raise uploads.UploadError(400, "uploads are disabled (no workspace)")
        return decoded

    def _save(self, task: Task, decoded: list[tuple[str, bytes]]) -> list[dict]:
        return uploads.save(self.workspace, task.id, decoded) if decoded else []

    def projects(self) -> "devmode.Projects":
        """Developer mode projects (<work folder>/projects/), or DevError if there is no work folder."""
        if self.workspace is None:
            raise devmode.DevError("no_workspace", "developer mode needs a work folder")
        with self._lock:
            if self._projects is None or self._projects.ws != Path(self.workspace).resolve():
                self._projects = devmode.Projects(self.workspace, deny=list(self.deny_paths))
            return self._projects

    def sandbox_on(self) -> bool:
        return self.control.sandbox_on() if self.control is not None else False

    def submit(self, text: str, files: Any = None, source: str = "chat", idc: bool | None = None,
               dev: str | None = None, lang: str | None = None) -> Task:
        if self.stopping.is_set():
            raise Busy("harness is shutting down")
        decoded = self._decode(files)          # validate everything before creating anything
        if dev is not None:
            self.projects().path(dev)          # DevError if the project does not exist
        task = Task(text, self.store, source)
        task.dev = dev
        task.ui_lang = i18n.normalize(lang) if lang else None
        with self._lock:
            task.idc = bool(self.settings["idc"] if idc is None else idc)
        saved = self._save(task, decoded)
        with self._lock:
            self._tasks[task.id] = task
        self._start(task, text, saved)
        return task

    def send(self, task_id: str, text: str, files: Any = None, lang: str | None = None) -> Task:
        """Continue a conversation with a new user message (same agent, history kept)."""
        if self.stopping.is_set():
            raise Busy("harness is shutting down")
        decoded = self._decode(files)
        task = self.get(task_id)
        if task is None:
            raise KeyError(task_id)
        with task._lock:
            if task.status not in TERMINAL:
                raise Busy(f"task is {task.status}")
            previous, task.status = task.status, "queued"   # reserve: a concurrent send now gets Busy
        if lang:
            task.ui_lang = i18n.normalize(lang)
        try:
            saved = self._save(task, decoded)
        except BaseException:
            with task._lock:
                task.status = previous
            raise
        self._start(task, text, saved)
        return task

    def _start(self, task: Task, text: str, saved: list[dict] | None = None) -> None:
        task.new_turn(text, uploads.public(saved or []))
        task.last_text = text          # the user's own words (language of the answer), without file notes
        if saved:   # one audit line per uploaded file (after the user message, so the chat reads in order)
            audit = TaskAudit(self.audit_path, task)
            for s in saved:
                audit.record(event="upload", agent="root", depth=0, path=s["path"], bytes=s["bytes"], sha256=s["sha256"])
        agent_text = uploads.describe(text, saved or [])
        threading.Thread(target=self._run, args=(task, agent_text), name=f"task-{task.id}", daemon=True).start()

    def running(self) -> int:
        with self._lock:
            return sum(1 for t in self._tasks.values() if t.status == "running")

    def _run(self, task: Task, text: str) -> None:
        def on_event(kind: str, data: dict) -> None:
            if kind == "assistant":
                task.add_event("message", agent=data.get("agent", "root"), content=data.get("content"),
                               final=data.get("final"), **{k: True for k in ("draft", "reviewed", "handoff")
                                                           if data.get(k)})
            elif kind == "stop":
                task.add_event("stop", agent=data.get("agent", "root"), reason=data.get("reason"))
            elif kind == "idc":
                task.add_event("idc", **{"agent": "root", **data})
            elif kind == "keys":   # key switch / pause (masked keys only): plain status in the chat + dashboard
                # masks only; "from_mask" (not "key_mask") so the stored history keeps the masked value readable
                ev = {k: v for k, v in data.items() if k in ("agent", "action", "to_mask", "seconds", "status",
                                                             "reason", "backup_kind")}
                if data.get("key_mask"):
                    ev["from_mask"] = data["key_mask"]
                task.add_event("keys", **{"agent": "root", **ev})
            elif kind == "critic":   # self-evaluation verdict (plain line in the trace)
                task.add_event("critic", agent="root", **{k: data.get(k) for k in ("critic", "round", "max", "ok",
                                                                                   "score", "issues")})
            elif kind == "retry":   # malformed tool call refused by the provider: asked again (plain line)
                task.add_event("retry", agent=data.get("agent", "root"), attempt=data.get("attempt"),
                               max=data.get("max"), reason=data.get("reason"))
            elif kind == "step":
                task.on_progress(data.get("agent", "root"), data.get("steps"), data.get("max_steps"),
                                 {k: data[k] for k in ("key", "key_mask", "key_task", "key_match") if k in data})

        # wait for a free slot (max_tasks), unless cancelled while queued
        while not self._slots.acquire(timeout=0.1):
            if task.cancel.is_set():
                task.result, task.stop_reason = "Cancelled while queued.", "cancelled"
                task.set_status("cancelled")
                task.add_event("status", status="cancelled")
                return
        try:
            if task.cancel.is_set():
                task.result, task.stop_reason = "Cancelled while queued.", "cancelled"
                task.set_status("cancelled")
                task.add_event("status", status="cancelled")
                return
            task.set_status("running")
            task.add_event("status", status="running")
            try:
                if task.agent is None:
                    agent = self.factory(task, TaskAudit(self.audit_path, task),
                                         HarnessConfirm(self.approvals, task, self), task.cancel, on_event)
                    if task.history and len(task.history) > 1:   # restored conversation: keep its context
                        agent.messages = agent.messages[:1] + [m for m in task.history[1:] if isinstance(m, dict)]
                    task.agent = agent
                self._sync_idc(task)
                self._sync_dev(task)
                res = task.agent.run(text)
                task.result, task.stop_reason = res.answer, res.stop_reason
                task.finish_turn(res)
                status = {"final": "done", "idc_collapse": "done", "cancelled": "cancelled"}.get(res.stop_reason, "stopped")
            except Exception as e:  # noqa: BLE001 - a task failure must not kill the server
                task.result, task.stop_reason, status = f"{type(e).__name__}: {e}", "error", "error"
            with task._lock:
                task.agents["root"]["answer"] = task.result
            task.set_status(status)
            task.add_event("status", status=status)
        finally:
            self._slots.release()

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list(self) -> list[dict]:
        with self._lock:
            tasks = list(self._tasks.values())
        return [t.snapshot(full=False) for t in tasks]   # the page puts pinned ones at the top

    # -- v0.9.5: pin, open the folder, delete
    def pin(self, task_id: str, pinned: bool) -> Task:
        task = self.get(task_id)
        if task is None:
            raise ConvError(404, "unknown", "unknown conversation")
        with task._lock:
            task.pinned = bool(pinned)
        task.save()
        return task

    def conv_folder(self, task: Task, create: bool = False) -> Path:
        """The conversation's folder, always inside the work folder (no symlink on the way)."""
        if self.workspace is None:
            raise ConvError(409, "no_workspace", "there is no work folder")
        root = Path(self.workspace).resolve()
        rel = conv_folder_rel(task.id, task.dev)
        if not re.fullmatch(r"(conversations/[0-9a-f]{6,32}|projects/[A-Za-z0-9][A-Za-z0-9._-]{0,63})", rel) \
                or ".." in rel:
            raise ConvError(400, "bad_folder", "invalid folder")
        d = root
        for part in rel.split("/"):
            d = d / part
            if d.is_symlink():
                raise ConvError(400, "symlink", "the folder goes through a link: refused")
            if create and not d.exists():
                d.mkdir(mode=0o700)
        real = d.resolve()
        if real != root and root not in real.parents:
            raise ConvError(400, "outside", "the folder is outside the work folder")
        for deny in self.deny_paths or []:
            dr = Path(deny).resolve()
            if real == dr or dr in real.parents:
                raise ConvError(400, "private", "private app data")
        return real

    def open_folder(self, task_id: str) -> dict:
        task = self.get(task_id)
        if task is None:
            raise ConvError(404, "unknown", "unknown conversation")
        path = self.conv_folder(task, create=True)
        opened = bool(self.folder_opener(path))
        self._audit(task, event="open_folder", agent="root", folder=conv_folder_rel(task.id, task.dev), opened=opened)
        return {"path": str(path), "rel": conv_folder_rel(task.id, task.dev), "opened": opened}

    def delete_task(self, task_id: str, delete_folder: bool = False) -> dict:
        import shutil
        task = self.get(task_id)
        if task is None:
            raise ConvError(404, "unknown", "unknown conversation")
        if task.status not in TERMINAL:
            raise ConvError(409, "running", "stop the conversation before deleting it")
        removed: list[str] = []
        if delete_folder and self.workspace is not None:
            if task.dev:
                with self._lock:
                    others = [t for t in self._tasks.values() if t is not task and t.dev == task.dev]
                if others:
                    raise ConvError(409, "shared", "this project is used by another conversation")
            root = Path(self.workspace).resolve()
            targets = [self.conv_folder(task)]
            if not task.dev:
                up = root / "uploads" / task.id
                if up.exists() and not up.is_symlink() and up.resolve().parent == (root / "uploads").resolve():
                    targets.append(up.resolve())
            for d in targets:
                if d.is_dir() and not d.is_symlink() and d != root:
                    shutil.rmtree(d)
                    removed.append(d.relative_to(root).as_posix())
        with self._lock:
            self._tasks.pop(task.id, None)
            for r in [r for r in self.rules.values() if r.get("task_id") == task.id]:
                self.rules.pop(r["id"], None)
                if self.store is not None:
                    self.store.delete("rules", r["id"])
        if self.store is not None:
            self.store.delete("tasks", task.id)          # also its events (journal)
        self._audit(None, event="conversation_deleted", task_id=task.id, folder_deleted=removed)
        return {"deleted": task.id, "folder_deleted": removed}

    def cancel(self, task_id: str) -> Task | None:
        task = self.get(task_id)
        if task is not None and task.status not in TERMINAL:
            task.cancel.set()     # the loop stops at its next step; pending approvals are denied
            task.add_event("status", status="cancelling")
        return task

    def cancel_all(self) -> None:
        with self._lock:
            tasks = list(self._tasks.values())
        for t in tasks:
            t.cancel.set()

    # -- emergency stop
    def stop_all(self, disable_schedules: bool = False) -> dict:
        """Cancel every task that is not finished, deny every pending approval (and optionally pause
        all schedules). Audit-logged."""
        with self._lock:
            active = [t for t in self._tasks.values() if t.status not in TERMINAL]
        for t in active:
            t.cancel.set()
        denied = self.approvals.deny_all()
        for t in active:
            t.add_event("status", status="cancelling", by="stop-all")
        paused = []
        if disable_schedules:
            with self._lock:
                for s in self.schedules.values():
                    if s["enabled"]:
                        s["enabled"] = False
                        paused.append(s["id"])
                        self._save_schedule(s)
        self._audit(None, event="stop_all", agent="user", tasks=[t.id for t in active],
                    approvals_denied=[a.id for a in denied], schedules_paused=paused)
        return {"cancelled": [t.id for t in active], "approvals_denied": [a.id for a in denied],
                "schedules_paused": paused}

    # -- remembered approval rules
    def match_rule(self, task_id: str, tool: str, category: str) -> dict | None:
        if category in NEVER_REMEMBER:
            return None
        with self._lock:
            for r in self.rules.values():
                if r["tool"] == tool and r["category"] == category and (
                        r["scope"] == "session" or r.get("task_id") == task_id):
                    return dict(r)
        return None

    def rule_used(self, rule: dict, task: Task, agent: str, tool: str, category: str) -> None:
        with self._lock:
            if rule["id"] in self.rules:
                self.rules[rule["id"]]["uses"] = self.rules[rule["id"]].get("uses", 0) + 1
        task.add_event("approval", agent=agent, approval=None, tool=tool, status="auto-approved", rule=rule["id"])
        self._audit(task, event="rule_applied", agent=agent, rule=rule["id"], scope=rule["scope"], tool=tool,
                    category=category)

    def add_rule(self, scope: str, tool: str, category: str, task: Task, approval_id: str | None = None) -> dict:
        if scope not in RULE_SCOPES:
            raise ValueError(f"scope must be one of {', '.join(RULE_SCOPES)}")
        if category in NEVER_REMEMBER:
            raise ValueError(f"'{category}' actions are always asked: they cannot be remembered")
        rule = {"id": uuid.uuid4().hex[:10], "scope": scope, "tool": tool, "category": category,
                "task_id": task.id, "created": _now(), "from_approval": approval_id, "uses": 0}
        with self._lock:
            self.rules[rule["id"]] = rule
        if self.store is not None and scope == "conversation":
            self.store.put("rules", rule["id"], rule)
        self._audit(task, event="rule_created", agent="user", rule=rule["id"], scope=scope, tool=tool,
                    category=category)
        return rule

    def revoke_rule(self, rule_id: str) -> dict:
        with self._lock:
            rule = self.rules.pop(rule_id)          # KeyError -> 404
        if self.store is not None:
            self.store.delete("rules", rule_id)
        self._audit(self.get(rule.get("task_id") or ""), event="rule_revoked", agent="user", rule=rule_id,
                    scope=rule["scope"], tool=rule["tool"], category=rule["category"])
        return rule

    def list_rules(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.rules.values()]

    def decide(self, approval_id: str, approve: bool, remember: str | None = None) -> tuple[Approval, dict | None]:
        ap = self.approvals.get(approval_id)
        if ap is None:
            raise KeyError(approval_id)
        if remember is not None:
            if not approve:
                raise ValueError("only an approval can be remembered")
            if remember not in RULE_SCOPES:
                raise ValueError(f"remember must be one of {', '.join(RULE_SCOPES)}")
            if ap.category in NEVER_REMEMBER:
                raise ValueError(f"'{ap.category}' actions are always asked: they cannot be remembered")
        rule = None
        task = self.get(ap.task_id)
        if remember is not None and task is not None and ap.status == "pending":
            # create (and audit) the rule BEFORE releasing the agent, so rule_created precedes any rule_applied
            rule = self.add_rule(remember, ap.tool, ap.category, task, ap.id)
        try:
            ap = self.approvals.decide(approval_id, approve)    # ValueError if no longer pending
        except ValueError:
            if rule is not None:                                # answered meanwhile: roll the rule back
                with self._lock:
                    self.rules.pop(rule["id"], None)
                if self.store is not None:
                    self.store.delete("rules", rule["id"])
                self._audit(task, event="rule_revoked", agent="user", rule=rule["id"], scope=rule["scope"],
                            tool=rule["tool"], category=rule["category"], reason="approval no longer pending")
            raise
        return ap, rule

    def active_router(self) -> Any:
        """Keys entered in the Settings page when there are some, else the providers.yaml router (or None)."""
        c = self.control
        if c is not None and c.router.entries and not c.demo():
            return c.router
        return self.key_router

    # -- "My files": the work folder as a simple list (download / add), for people who never open folders
    def list_files(self, limit: int = FILES_LIST_MAX) -> dict:
        """Regular files of the work folder, newest first. Hidden entries and symlinks are skipped."""
        import os
        root = Path(self.workspace).resolve()
        out: list[dict] = []
        truncated = False
        for d, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(x for x in dirs if not x.startswith(".") and not (Path(d) / x).is_symlink())
            if len(Path(d).relative_to(root).parts) >= 6:
                dirs[:] = []
            for name in files:
                f = Path(d) / name
                if name.startswith(".") or f.is_symlink() or not f.is_file():
                    continue
                st = f.stat()
                out.append({"path": f.relative_to(root).as_posix(), "name": name, "bytes": st.st_size,
                            "mtime": int(st.st_mtime), "upload": f.relative_to(root).parts[0] == "uploads"})
                if len(out) >= limit * 4:
                    truncated = True
                    break
            if truncated:
                break
        out.sort(key=lambda x: (-x["mtime"], x["path"]))
        return {"files": out[:limit], "truncated": truncated or len(out) > limit, "folder": str(root)}

    def workspace_path(self, rel: str) -> Path:
        """A regular, non-hidden file inside the work folder (no symlink, no escape), else FileNotFoundError."""
        if self.workspace is None or not rel or "\x00" in rel:
            raise FileNotFoundError(rel)
        root = Path(self.workspace).resolve()
        cand = root / rel
        parts = Path(rel).parts
        if Path(rel).is_absolute() or any(x in ("..", "") or x.startswith(".") for x in parts):
            raise FileNotFoundError(rel)
        cur = root
        for x in parts:
            cur = cur / x
            if cur.is_symlink():
                raise FileNotFoundError(rel)
        path = cand.resolve()
        if root not in path.parents or not path.is_file():
            raise FileNotFoundError(rel)
        return path

    def add_files(self, files: Any) -> list[dict]:
        """Files added from "My files" (not attached to a message): saved at the top of the work folder."""
        if self.workspace is None:
            raise uploads.UploadError(400, "uploads are disabled (no workspace)")
        decoded = uploads.decode(files, self.upload_limits)
        if not decoded:
            raise uploads.UploadError(400, "no file")
        saved = uploads.public(uploads.save_in(Path(self.workspace), decoded))
        self._audit(None, event="files_added", files=[x["path"] for x in saved])
        return saved

    # -- usage
    def usage(self) -> dict:
        with self._lock:
            tasks = list(self._tasks.values())
        convs, total = [], _zero()
        for t in tasks:
            rep = t.usage_report()
            _add(total, rep["total"])
            convs.append({"id": t.id, "task": t.text[:120], "status": t.status, "turns": t.turns,
                          "source": t.source, **rep})
        r = self.active_router()
        keys = r.status() if r is not None else None
        return {"total": total, "conversations": convs, "keys": keys}

    # -- export
    def audit_for(self, task_id: str) -> list[dict]:
        out = []
        if self.audit_path.exists():
            with open(self.audit_path, encoding="utf-8") as f:
                for line in f:
                    if task_id in line:
                        try:
                            e = json.loads(line)
                        except ValueError:
                            continue
                        if e.get("task_id") == task_id:
                            out.append(e)
        return out

    def export(self, task_id: str, fmt: str = "json", lang: str = "en") -> tuple[str, bytes, str]:
        task = self.get(task_id)
        if task is None:
            raise KeyError(task_id)
        snap = task.snapshot()
        events, _ = task.events_since(0)
        b = export.bundle(snap, events, self.audit_for(task_id), task.usage_report())
        if fmt == "md":
            return f"conversation-{task_id}.md", export.markdown(b, lang).encode("utf-8"), "text/markdown; charset=utf-8"
        return (f"conversation-{task_id}.json", json.dumps(b, ensure_ascii=False, indent=2).encode("utf-8"),
                "application/json; charset=utf-8")

    # -- schedules
    def _save_schedule(self, s: dict) -> None:
        if self.store is not None:
            self.store.put("schedules", s["id"], s)

    def add_schedule(self, data: dict) -> dict:
        s = schedule.new(data, self.clock(), data.get("name") if isinstance(data.get("name"), str) else None)
        with self._lock:
            self.schedules[s["id"]] = s
            self._save_schedule(s)
        self._audit(None, event="schedule_created", agent="user", schedule=s["id"], when=schedule.describe(s),
                    prompt=s["prompt"])
        return dict(s)

    def update_schedule(self, sid: str, enabled: bool) -> dict:
        with self._lock:
            s = self.schedules[sid]
            s["enabled"] = bool(enabled)
            if enabled and s["next_run"] <= self.clock():    # re-enabled late: next slot from now, no burst
                s["next_run"] = schedule.next_run(s, self.clock())
            self._save_schedule(s)
        self._audit(None, event="schedule_enabled" if enabled else "schedule_disabled", agent="user", schedule=sid)
        return dict(s)

    def delete_schedule(self, sid: str) -> dict:
        with self._lock:
            s = self.schedules.pop(sid)
        if self.store is not None:
            self.store.delete("schedules", sid)
        self._audit(None, event="schedule_deleted", agent="user", schedule=sid)
        return s

    def list_schedules(self) -> list[dict]:
        with self._lock:
            return [dict(s, when=schedule.describe(s)) for s in self.schedules.values()]

    def run_schedule(self, sid: str, now: float | None = None, manual: bool = False) -> Task | None:
        """Start one run of a schedule (a new conversation). Skipped while its previous run is active."""
        now = self.clock() if now is None else now
        with self._lock:
            s = self.schedules[sid]
            prev = self._tasks.get(s.get("last_task") or "")
            if not manual:
                s["next_run"] = schedule.next_run(s, max(now, s["next_run"]))
            if prev is not None and prev.status not in TERMINAL:
                s["skipped"] = s.get("skipped", 0) + 1
                self._save_schedule(s)
                skipped = True
            else:
                skipped = False
        if skipped:
            self._audit(prev, event="schedule_skipped", agent="scheduler", schedule=sid,
                        reason="previous run still active")
            return None
        task = self.submit(s["prompt"], source=f"schedule:{sid}")
        with self._lock:
            s["last_run"], s["last_task"], s["runs"] = now, task.id, s.get("runs", 0) + 1
            self._save_schedule(s)
        self._audit(task, event="schedule_run", agent="scheduler", schedule=sid, manual=manual)
        return task

    def run_due(self, now: float | None = None) -> list[Task]:
        now = self.clock() if now is None else now
        with self._lock:
            due = [s["id"] for s in self.schedules.values() if s["enabled"] and s["next_run"] <= now]
        out = []
        for sid in due:
            try:
                t = self.run_schedule(sid, now)
            except (KeyError, Busy):
                continue
            if t is not None:
                out.append(t)
        return out

    def _scheduler_loop(self, tick: float) -> None:
        while not self.stopping.wait(tick):
            try:
                self.run_due()
            except Exception as e:  # noqa: BLE001 - never let the scheduler thread die
                print(f"scheduler: {type(e).__name__}: {e}", file=sys.stderr)

    # -- per-minute counter (v0.8.1)
    def rate_view(self) -> dict:
        """Per key (MASKED): tokens / requests left this minute, from the provider's x-ratelimit-* headers
        (source "provider") or estimated from the tokens used in the last 60 s (source "estimate")."""
        router = self.active_router()
        if router is None:
            return {"mode": "demo" if (self.control is not None and self.control.effective_mode() == "demo")
                    else "single-key (.env)", "keys": []}
        keys = [{f: k.get(f) for f in ("name", "key", "provider", "available", "cooldown_s", "refused", "rate",
                                        "categories", "agents")}
                for k in router.status().get("keys", [])]
        return {"mode": "settings" if router is not self.key_router else "router", "keys": keys}

    # -- health
    def health(self, check_backend: bool = False, timeout: float = 3.0) -> dict:
        with self._lock:
            counts: dict[str, int] = {}
            for t in self._tasks.values():
                counts[t.status] = counts.get(t.status, 0) + 1
            n_sched = sum(1 for s in self.schedules.values() if s["enabled"])
        router = self.active_router()
        if self.control is not None and (self.control.demo() or (router is None and self.control.effective_mode() == "demo")):
            keys = {"mode": "demo", "provider": "mock", "model": "mock", "key": None}
            urls = []
        elif router is not None:
            st = router.status()
            keys = {"mode": "settings" if router is not self.key_router else "router",
                    "keys": [{f: k.get(f) for f in ("name", "provider", "key", "key_env",
                                                    "categories", "available", "cooldown_s")}
                             for k in st.get("keys", [])]}
            urls = sorted({k.base_url for k in router.entries if getattr(k, "base_url", None)})
        else:
            keys = {"mode": "single-key (.env)", "provider": self.backend.get("provider"),
                    "model": self.backend.get("model"), "key": self.backend.get("key")}
            urls = [self.backend["base_url"]] if self.backend.get("base_url") else []
        backend: dict[str, Any] = {"checked": False, "urls": urls}
        if check_backend:
            backend = {"checked": True, "results": [_probe(u, timeout) for u in urls]}
        return {"status": "stopping" if self.stopping.is_set() else "ok", "version": __version__,
                "uptime_s": round(self.clock() - self.started, 1), "tasks": counts,
                "running": counts.get("running", 0), "max_tasks": self.max_tasks,
                "pending_approvals": self.approvals.pending_count(), "rules": len(self.rules),
                "schedules_enabled": n_sched,
                "persistence": str(self.store.path) if self.store is not None else None,
                "uploads": self.workspace is not None, "keys": keys, "backend": backend,
                "idc": {"default": self.settings["idc"]},
                "critic": {"enabled": bool(self.settings.get("critic")), "rounds": self.settings.get("critic_rounds")},
                "memory": self._memory_status(), "tls": _tls_status()}

    def _memory_status(self) -> dict:
        try:
            return self.memory.status() if self.memory is not None else {"semantic": False}
        except Exception:  # noqa: BLE001
            return {"semantic": False}

    def shutdown(self, wait: float = 10.0) -> None:
        """Cancel everything and give running turns a moment to stop (temp workspace copies are removed)."""
        self.stopping.set()
        self.cancel_all()
        with self._lock:
            for t in self._tasks.values():
                with t._lock:
                    t._lock.notify_all()
        end = time.monotonic() + wait
        while time.monotonic() < end:
            with self._lock:
                busy = any(t.status in ("running", "cancelling") for t in self._tasks.values())
            if not busy:
                return
            time.sleep(0.05)


def _probe(url: str, timeout: float) -> dict:
    """Reachability only: GET <base_url>/models WITHOUT any API key. Any HTTP answer = reachable."""
    import urllib.error
    import urllib.request
    target = url.rstrip("/") + "/models"
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(urllib.request.Request(target, method="GET"), timeout=timeout) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"url": url, "reachable": False, "error": f"{type(e).__name__}: {getattr(e, 'reason', e)}"}
    return {"url": url, "reachable": True, "http_status": code, "ms": round((time.monotonic() - t0) * 1000)}


# ---------------------------------------------------------------------------- HTTP
FILE_VIEW_MAX = 2 * 1024 * 1024
CONV_RE = re.compile(r"^/conv/([0-9a-f]{6,32})/(pin|folder|delete)$")
TASK_RE = re.compile(r"^/tasks/([0-9a-f]+)(/events|/cancel|/messages|/stream|/export|/idc|/graph|/file)?$")
APPROVAL_RE = re.compile(r"^/approvals/([0-9a-f]+)$")
RULE_RE = re.compile(r"^/rules/([0-9a-f]+)/revoke$")
SCHEDULE_RE = re.compile(r"^/schedules/([0-9a-f]+)(/run|/delete)?$")
APIS_RE = re.compile(r"^/app/apis(?:/([0-9a-f]+))?(/delete|/spec)?$")
PROVIDER_RE = re.compile(r"^/app/providers/([0-9a-f]+)(/delete|/test)?$")
CSRF_HEADER = "X-CSRF-Token"


def remote_settings_enabled() -> bool:
    import os
    return os.environ.get("AGENT_REMOTE_SETTINGS", "").strip().lower() in ("1", "true", "yes", "on")
SSE_PING = 15.0


LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def _tls_status() -> dict:
    """v0.9.4: where HTTPS certificates come from (system / bundled / macos-keychain / env / missing)."""
    from . import tlsca
    return {"source": tlsca.STATE.get("source"), "bundled": tlsca._certifi() is not None}
# v0.9.3: the app's own pages. Everything comes from this app (no CDN); nobody else may frame them.
PAGE_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; media-src 'self' data: blob:; connect-src 'self'; frame-src 'self'; "
            "worker-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'")


def make_handler(h: Harness, token: str | None, local_only: bool, auth: "remote.Auth | None" = None):
    auth = auth or remote.Auth(token)
    class Handler(BaseHTTPRequestHandler):
        server_version = "autonomous-agent-harness"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # quiet
            pass

        def _send(self, code: int, obj: Any = None, body: bytes | None = None,
                  ctype: str = "application/json; charset=utf-8", extra: dict | None = None) -> None:
            if body is None:
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            extra = dict(extra or {})
            cache = extra.pop("Cache-Control-Override", "no-store")
            if ctype.startswith("text/html"):         # v0.9.3: no clickjacking of approval cards, strict sources
                keys = {k.lower() for k in extra}
                if "x-frame-options" not in keys:
                    extra["X-Frame-Options"] = "DENY"
                if "content-security-policy" not in keys:
                    extra["Content-Security-Policy"] = PAGE_CSP
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            for k, v in extra.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")     # a ?pair= code never leaks via Referer
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self) -> bool:
            if not local_only:
                return True
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            return host in LOCAL_HOSTS

        def _direct_local(self) -> bool:
            """A request from this computer itself, not relayed by a proxy or tunnel."""
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            return (self.client_address[0] in LOOPBACK and host in LOCAL_HOSTS
                    and not any(self.headers.get(x) for x in remote.FORWARD_HEADERS))

        def _secure(self) -> bool:
            if self.client_address[0] not in LOOPBACK:
                return False
            fwd = (self.headers.get("X-Forwarded-Proto") or "").lower()
            return fwd == "https" or "proto=https" in (self.headers.get("Forwarded") or "").lower()

        def _client(self) -> str:
            peer = self.client_address[0]
            if peer in LOOPBACK:
                relayed = (self.headers.get("Cf-Connecting-Ip") or
                           (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip())
                if relayed:
                    return "via-proxy:" + relayed
            return peer

        def _who(self, query_token: str | None = None) -> str | None:
            """How this request is authenticated: token | cookie | local | open, or None (refused)."""
            hdr = self.headers.get("Authorization", "")
            if hdr.startswith("Bearer ") and auth.check_token(hdr[7:]):
                return "token"
            if query_token is not None and auth.check_token(query_token):   # EventSource: /stream only
                return "token"
            if auth.check_session(remote.cookie_value(self.headers.get("Cookie"))):
                return "cookie"
            if not auth.required:
                return "open"
            if auth.remote and auth.local_trusted and self._direct_local():
                return "local"
            return None

        def _origin_ok(self) -> bool:
            origin = self.headers.get("Origin")
            if not origin:
                return True
            hosts = {self.headers.get("Host"), self.headers.get("X-Forwarded-Host")}
            if h.public_url:
                hosts.add(urlparse(h.public_url).netloc)
            return urlparse(origin).netloc in hosts

        def _settings_allowed(self) -> bool:
            """Settings / keys / restart: this computer only, unless AGENT_REMOTE_SETTINGS=1 and signed in."""
            if self._direct_local():
                return True
            return remote_settings_enabled() and self._who() in ("token", "cookie")

        def _csrf(self) -> str:
            import hashlib
            import hmac as _hmac
            who = self._who() or "none"
            subject = remote.cookie_value(self.headers.get("Cookie")) if who == "cookie" else who
            secret = h.control.csrf_secret if h.control is not None else h.csrf_secret
            return _hmac.new(secret, (subject or "").encode(), hashlib.sha256).hexdigest()[:40]

        def _app_get(self, path: str) -> None:
            c = h.control
            if path == "/app/status":
                if c is None:
                    return self._send(200, {"available": False, "editable": False, "first_run": False})
                return self._send(200, {"available": True, **c.status(), "editable": self._settings_allowed(),
                                        "local": self._direct_local(), "remote_settings": remote_settings_enabled(),
                                        "csrf": self._csrf()})
            if c is None:
                return self._send(404, {"error": "settings are not available in this mode"})
            if not self._settings_allowed():
                return self._send(403, {"error": "settings can only be changed from the computer running the agent "
                                                 "(set AGENT_REMOTE_SETTINGS=1 to allow signed-in devices)", "locked": True,
                                        "code": "locked"})
            if path == "/app/settings":
                return self._send(200, c.view())
            if path == "/app/providers":
                return self._send(200, {"providers": c.providers_view(), "storage": c.secrets.backend,
                                        "currency": c.router.currency})
            if path == "/app/pool":
                return self._send(200, c.pool_view())
            if path == "/app/apis":
                reg = getattr(c, "apis", None)
                if reg is None:
                    return self._send(404, {"error": "business APIs are not available in this mode"})
                return self._send(200, {"apis": reg.view(), "storage": c.secrets.backend})
            return self._send(404, {"error": "not found"})

        def _audit_api(self, action: str, out: dict) -> None:
            h._audit(None, event="settings_api", agent="user", action=action.strip("/"), api=out.get("name") or out.get("id"),
                     base_url=out.get("base_url"), auto_get=out.get("auto_get"), spends=out.get("spends"))

        def _conv_post(self, task_id: str, action: str, data: dict) -> None:
            """v0.9.5: pin / open the folder / delete a conversation. CSRF token required; the folder is
            computed here from the conversation (no path from the page) and opened on this computer only."""
            import hmac as _hmac
            if not _hmac.compare_digest(str(self.headers.get(CSRF_HEADER) or ""), self._csrf()):
                return self._send(403, {"error": "missing or invalid CSRF token (reload the page)", "csrf": True,
                                        "code": "csrf"})
            try:
                if action == "pin":
                    if not isinstance(data.get("pinned"), bool):
                        return self._send(400, {"error": "'pinned' must be true or false"})
                    return self._send(200, h.pin(task_id, data["pinned"]).snapshot(full=False))
                if action == "folder":
                    if not self._direct_local():
                        return self._send(403, {"error": "the folder opens on the computer running the app",
                                                "code": "local_only"})
                    return self._send(200, h.open_folder(task_id))
                if action == "delete":
                    df = data.get("delete_folder", False)
                    if not isinstance(df, bool):
                        return self._send(400, {"error": "'delete_folder' must be true or false"})
                    return self._send(200, h.delete_task(task_id, df))
            except ConvError as e:
                return self._send(e.status, {"error": str(e), "code": e.code})
            except OSError as e:
                return self._send(500, {"error": f"folder error: {e.strerror or e}", "code": "os"})
            return self._send(404, {"error": "not found"})

        def _app_post(self, path: str, data: dict) -> None:
            import hmac as _hmac
            c = h.control
            if c is None:
                return self._send(404, {"error": "settings are not available in this mode"})
            if not self._settings_allowed():
                return self._send(403, {"error": "settings can only be changed from the computer running the agent "
                                                 "(set AGENT_REMOTE_SETTINGS=1 to allow signed-in devices)", "locked": True,
                                        "code": "locked"})
            if not _hmac.compare_digest(str(self.headers.get(CSRF_HEADER) or ""), self._csrf()):
                return self._send(403, {"error": "missing or invalid CSRF token (reload the page)", "csrf": True, "code": "csrf"})
            try:
                if path == "/app/settings":
                    return self._send(200, c.update(data))
                if path == "/app/setup":
                    return self._send(200, c.setup(data))
                if path == "/app/providers":
                    return self._send(201, c.save_provider(data))
                if path == "/app/providers/test":
                    return self._send(200, c.test_provider(data=data))
                if path == "/app/providers/order":
                    return self._send(200, {"providers": c.reorder(data.get("ids"))})
                if path == "/app/providers/bulk":     # many keys at once: parse, test all, save the good ones
                    return self._send(200, c.bulk_add(data.get("text"), save=data.get("save", True) is not False))
                if path == "/app/providers/propose":
                    return self._send(200, {"proposal": c.propose_tasks()})
                if path == "/app/providers/tasks":
                    return self._send(200, {"providers": c.set_tasks(data.get("assign"))})
                if path == "/app/remote/token":
                    return self._send(200, c.new_token())
                if path in ("/app/restart", "/app/quit"):
                    if not c.request_stop(path == "/app/restart"):
                        return self._send(409, {"error": "restart / quit is not available in this mode", "code": "no_restart"})
                    return self._send(202, {"ok": True, "restart": path == "/app/restart"})
                ma = APIS_RE.match(path)
                if ma:
                    reg = getattr(c, "apis", None)
                    if reg is None:
                        return self._send(404, {"error": "business APIs are not available in this mode"})
                    aid, action = ma.group(1), ma.group(2)
                    if action == "/delete":
                        out = reg.delete(aid)
                    elif action == "/spec":
                        n = reg.load_spec(reg.find(aid))
                        out = {"endpoints": n, **next(v for v in reg.view() if v["id"] == reg.find(aid)["id"])}
                    else:
                        out = reg.save(data, aid)
                    self._audit_api(action or ("/add" if not aid else "/edit"), out)
                    return self._send(201 if not aid else 200, out)
                m = PROVIDER_RE.match(path)
                if m:
                    pid, action = m.group(1), m.group(2)
                    if action == "/delete":
                        return self._send(200, c.delete_provider(pid))
                    if action == "/test":
                        return self._send(200, c.test_provider(pid))
                    return self._send(200, c.save_provider(data, pid))
            except KeyError:
                return self._send(404, {"error": "unknown key", "code": "unknown_key"})
            except ValueError as e:
                return self._send(400, {"error": str(e), "code": getattr(e, "code", None), "params": getattr(e, "params", {})})
            return self._send(404, {"error": "not found"})

        def _guard(self, post: bool, query_token: str | None = None) -> bool:
            if not self._host_ok():
                self._send(403, {"error": "bad Host header"})
                return False
            if post:
                if not self._origin_ok():
                    self._send(403, {"error": "cross-origin request refused"})
                    return False
                if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                    self._send(415, {"error": "Content-Type must be application/json"})
                    return False
            who = self._who(query_token)
            if who is None:
                self._send(401, {"error": "sign in required (token, or a pairing code at /connect)"})
                return False
            if post and who == "cookie" and not self.headers.get("Origin"):
                self._send(403, {"error": "cross-origin request refused (no Origin)"})
                return False
            return True

        def _base_url(self) -> str:
            if h.public_url:
                return h.public_url.rstrip("/") + "/"
            fh = self.headers.get("X-Forwarded-Host")
            if fh and self.client_address[0] in LOOPBACK:
                return f"{'https' if self._secure() else 'http'}://{fh}/"
            return f"http://{self.headers.get('Host') or '127.0.0.1'}/"

        def _auth_routes(self, path: str, data: dict) -> bool:
            """POST /auth/*; returns False if `path` is not one of them."""
            if path == "/auth/login":
                if not self._origin_ok():
                    self._send(403, {"error": "cross-origin request refused"})
                    return True
                if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                    self._send(415, {"error": "Content-Type must be application/json"})
                    return True
                if not auth.required:
                    self._send(200, {"ok": True, "required": False})
                    return True
                try:
                    sid = auth.login(self._client(), token=data.get("token"), pair=data.get("pair"))
                except remote.RateLimited as e:
                    self._send(429, {"error": str(e)}, extra={"Retry-After": str(e.retry_after)})
                    return True
                except remote.LoginError as e:
                    self._send(401, {"error": str(e)})
                    return True
                h._audit(None, event="remote_login", via="pair" if data.get("pair") else "token",
                         client=self._client())
                self._send(200, {"ok": True}, extra={"Set-Cookie": auth.cookie(sid, self._secure())})
                return True
            if path == "/auth/logout":
                if not self._origin_ok():
                    self._send(403, {"error": "cross-origin request refused"})
                    return True
                auth.logout(remote.cookie_value(self.headers.get("Cookie")))
                self._send(200, {"ok": True}, extra={"Set-Cookie": auth.clear_cookie(self._secure())})
                return True
            if path in ("/auth/pair", "/auth/revoke-all"):
                if not self._guard(post=True):
                    return True
                if path == "/auth/revoke-all":
                    n = auth.revoke_all()
                    h._audit(None, event="remote_revoke_all", sessions=n)
                    self._send(200, {"ok": True, "sessions": n},
                               extra={"Set-Cookie": auth.clear_cookie(self._secure())})
                    return True
                if not auth.required:
                    self._send(400, {"error": "no token is set: nothing to pair (use --remote)"})
                    return True
                code, exp = auth.new_pairing()
                url = self._base_url() + "connect?pair=" + code
                h._audit(None, event="remote_pairing_code", client=self._client())
                self._send(200, {"code": code, "url": url, "expires_in": int(exp - auth.clock()),
                                 "public_url": h.public_url, "svg": qr.to_svg(qr.encode(url), scale=6)})
                return True
            return False

        def _body(self) -> dict | None:
            n = int(self.headers.get("Content-Length") or 0)
            if n > h.max_body:
                self._send(413, {"error": "body too large"})
                return None
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except (ValueError, UnicodeDecodeError):
                self._send(400, {"error": "invalid JSON"})
                return None
            if not isinstance(data, dict):
                self._send(400, {"error": "JSON object expected"})
                return None
            return data

        def _text(self, data: dict, key: str) -> str | None:
            """The message text; may be empty only if files are attached."""
            text = data.get(key)
            if text is None and data.get("files"):
                text = ""
            if not isinstance(text, str) or (not text.strip() and not data.get("files")):
                self._send(400, {"error": f"'{key}' (non-empty string) is required"})
                return None
            if len(text) > MAX_TASK_CHARS:
                self._send(400, {"error": f"{key} too long"})
                return None
            return text.strip() or "Please look at the attached file(s)."

        def _stream(self, task: Task, q: dict) -> None:
            """Server-Sent Events: one `data:` JSON line per task event, `id:` = seq. Resumes after
            Last-Event-ID (or ?since=N). Ends when the client goes away or the harness stops."""
            try:
                since = int(self.headers.get("Last-Event-ID") or -1) + 1 or int((q.get("since") or ["0"])[0])
            except ValueError:
                since = 0
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            last = time.monotonic()
            once = (q.get("once") or ["0"])[0] == "1"     # tests / curl: stop once the turn is finished
            try:
                self.wfile.write(b"retry: 2000\n\n")
                self.wfile.flush()
                while not h.stopping.is_set():
                    events, nxt = task.wait_events(since, 1.0)
                    for e in events:
                        self.wfile.write(f"id: {e['seq']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n".encode())
                    if events:
                        last = time.monotonic()
                    elif time.monotonic() - last > SSE_PING:
                        self.wfile.write(b": ping\n\n")
                        last = time.monotonic()
                    self.wfile.flush()
                    since = nxt
                    if once and task.status in TERMINAL and not events:
                        break
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass

        def _task_file(self, task: Task, rel: str, download: bool = False) -> None:
            """A file written during the current turn of this conversation (swarm graph link), read-only."""
            if h.workspace is None or not rel or rel not in task.graph()["files"]:
                return self._send(404, {"error": "not a file written in this turn"})
            root = Path(h.workspace).resolve()
            path = (root / rel).resolve()
            if root not in path.parents or not path.is_file():
                return self._send(404, {"error": "file not found"})
            if path.stat().st_size > FILE_VIEW_MAX:
                return self._send(413, {"error": "file too large to view"})
            data = path.read_bytes()
            try:
                data.decode("utf-8")
                ctype = "text/plain; charset=utf-8"
            except UnicodeDecodeError:
                ctype = "application/octet-stream"
            name = re.sub(r'[^A-Za-z0-9._-]', "_", path.name) or "file"
            self._send(200, body=data, ctype=ctype,
                       extra={"Content-Disposition": f'{"attachment" if download else "inline"}; filename="{name}"',
                              "Content-Security-Policy": "sandbox; default-src 'none'"})

        def _workspace_file(self, rel: str) -> None:
            """Download one file of the work folder ("My files"), as an attachment."""
            try:
                path = h.workspace_path(rel)
            except FileNotFoundError:
                return self._send(404, {"error": "file not found"})
            if path.stat().st_size > FILE_DOWNLOAD_MAX:
                return self._send(413, {"error": "file too large to download here"})
            name = re.sub(r'[^\w.() -]', "_", path.name, flags=re.UNICODE) or "file"
            ascii_name = re.sub(r'[^A-Za-z0-9._-]', "_", path.name) or "file"
            from urllib.parse import quote
            self._send(200, body=path.read_bytes(), ctype="application/octet-stream",
                       extra={"Content-Disposition": f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(name)}',
                              "Content-Security-Policy": "sandbox; default-src 'none'"})

        def _preview(self, raw: str) -> None:
            """/preview/<token>/<project>/<file>: a project file for the sandboxed preview iframe. The token
            (HMAC of the project name with a per-run secret) is the authorization, so it also works in remote
            mode; responses carry a CSP sandbox (opaque origin, no network, no form posts)."""
            if not self._host_ok():
                return self._send(403, {"error": "bad Host header"})
            parts = raw.split("/", 4)          # "", "preview", token, project, rest
            if len(parts) < 4:
                return self._send(404, {"error": "not found"})
            if len(parts) == 4:                # /preview/<tok>/<project> -> trailing slash for relative links
                return self._send(301, {"moved": raw + "/"}, extra={"Location": raw + "/"})
            try:
                body, ctype = h.projects().preview_file(parts[2], parts[3], parts[4])
            except devmode.DevError as e:
                return self._send(404, body=b"Not found", ctype="text/plain; charset=utf-8",
                                  extra={"Content-Security-Policy": "sandbox; default-src 'none'"}) if e.code != "too_big" else \
                    self._send(413, {"error": str(e)})
            self._send(200, body=body, ctype=ctype, extra={"Content-Security-Policy": devmode.PREVIEW_CSP,
                                                         "X-Frame-Options": "SAMEORIGIN"})

        def do_GET(self) -> None:  # noqa: N802
            u = urlparse(self.path)
            path, q = u.path.rstrip("/") or "/", parse_qs(u.query)
            asset = pwa.asset(path)
            if asset is not None:
                ctype, body, cache = asset
                return self._send(200, body=body, ctype=ctype, extra={"Cache-Control-Override": cache})
            if path == "/auth/status":
                who = self._who()
                return self._send(200, {"authenticated": who is not None, "via": who, "remote": auth.remote,
                                        "required": auth.required, "public_url": h.public_url})
            html_settings = path == "/settings" and "text/html" in (self.headers.get("Accept") or "")
            if path.startswith("/preview/"):
                return self._preview(u.path)
            if path in ("/", "/chat", "/dashboard", "/connect", "/welcome", "/help", "/dev") or html_settings:
                page = {"/dashboard": PAGE, "/connect": CONNECT_PAGE, "/settings": SETTINGS_PAGE,
                        "/welcome": WELCOME_PAGE, "/help": HELP_PAGE, "/dev": DEV_PAGE}.get(path, CHAT_PAGE)
                if self._host_ok():
                    lang = (q.get("lang") or [None])[0]
                    default = h.control.cfg.get("lang") if h.control is not None else None
                    theme = h.control.theme() if h.control is not None else None
                    self._send(200, body=render_page(page, lang, default, theme), ctype="text/html; charset=utf-8")
                else:
                    self._send(403, {"error": "bad Host header"})
                return
            m = TASK_RE.match(path)
            qtok = (q.get("access_token") or [None])[0] if m and m.group(2) == "/stream" else None
            if not self._guard(post=False, query_token=qtok if qtok and not self.headers.get("Authorization") else None):
                return
            if path == "/tasks":
                return self._send(200, {"tasks": h.list()})
            if path.startswith("/app/"):
                return self._app_get(path)
            if path == "/health":
                return self._send(200, h.health(check_backend=(q.get("check") or ["0"])[0] in ("1", "true", "yes")))
            if path == "/usage":
                return self._send(200, h.usage())
            if path == "/rules":
                return self._send(200, {"rules": h.list_rules(), "never_remembered": list(NEVER_REMEMBER)})
            if path == "/schedules":
                return self._send(200, {"schedules": h.list_schedules()})
            if path == "/mcp":
                return self._send(200, {"servers": h.mcp.list_servers()})
            if path == "/settings":
                return self._send(200, h.get_settings())
            if path == "/conv/csrf":    # v0.9.5: token for the conversation actions (same-origin pages only)
                return self._send(200, {"csrf": self._csrf()})
            if path == "/keys/rate":   # v0.8.1: tokens / requests left per minute, per key (masked)
                return self._send(200, h.rate_view())
            if path == "/keys":
                router = h.active_router()
                if router is None:
                    demo = h.control is not None and h.control.effective_mode() == "demo"
                    return self._send(200, {"mode": "demo" if demo else "single-key (.env)", "keys": [], "categories": {}})
                par = h.control.parallel_limit("text") if h.control is not None else None
                return self._send(200, {"mode": "settings" if router is not h.key_router else "router", **router.status(),
                                        **({"parallel": par} if par else {})})
            if path == "/files":
                if h.workspace is None:
                    return self._send(200, {"available": False, "files": []})
                return self._send(200, {"available": True, **h.list_files()})
            if path == "/files/download":
                return self._workspace_file((q.get("path") or [""])[0])
            if path == "/dev/projects":
                try:
                    return self._send(200, {"available": True, "projects": h.projects().list(),
                                            "sandbox": h.sandbox_on(), "python": bool(sandbox_mod.python_exe())})
                except devmode.DevError:
                    return self._send(200, {"available": False, "projects": [], "sandbox": h.sandbox_on()})
            if path == "/dev/zip":
                try:
                    body, name = h.projects().zip((q.get("project") or [""])[0])
                except devmode.DevError as e:
                    return self._send(404 if e.code in ("no_project", "bad_name") else 400, {"error": str(e), "code": e.code})
                h._audit(None, event="dev_zip", project=name, bytes=len(body))
                return self._send(200, body=body, ctype="application/zip",
                                  extra={"Content-Disposition": f'attachment; filename="{name}"',
                                         "Content-Security-Policy": "sandbox; default-src 'none'"})
            if path == "/config":
                lim = h.upload_limits
                return self._send(200, {"uploads": h.workspace is not None, "sandbox": h.sandbox_on(),
                                        "max_upload_bytes": lim.max_file_bytes,
                                        "max_message_bytes": lim.max_message_bytes})
            if path == "/approvals":
                return self._send(200, {"approvals": h.approvals.list(pending_only="all" not in q)})
            if m and m.group(2) in (None, "/events", "/stream", "/export", "/graph", "/file"):
                task = h.get(m.group(1))
                if task is None:
                    return self._send(404, {"error": "unknown task"})
                if m.group(2) == "/graph":
                    return self._send(200, task.graph())
                if m.group(2) == "/file":
                    return self._task_file(task, (q.get("path") or [""])[0],
                                           download=(q.get("download") or ["0"])[0] == "1")
                if m.group(2) == "/stream":
                    return self._stream(task, q)
                if m.group(2) == "/export":
                    fmt = (q.get("format") or ["json"])[0]
                    if fmt not in export.FORMATS:
                        return self._send(400, {"error": "format must be json or md"})
                    name, body, ctype = h.export(task.id, fmt, (q.get("lang") or ["en"])[0])
                    return self._send(200, body=body, ctype=ctype,
                                      extra={"Content-Disposition": f'attachment; filename="{name}"'})
                if m.group(2) == "/events":
                    try:
                        since = int((q.get("since") or ["0"])[0])
                    except ValueError:
                        since = 0
                    events, nxt = task.events_since(since)
                    return self._send(200, {"events": events, "next": nxt, "status": task.status})
                snap = task.snapshot()
                if h.workspace is not None:     # v0.9.5: the folder's full path, shown (copyable) in the chat
                    snap["folder_path"] = str(Path(h.workspace).resolve() / snap["folder"])
                return self._send(200, snap)
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path.rstrip("/")
            if path.startswith("/auth/"):
                if not self._host_ok():
                    return self._send(403, {"error": "bad Host header"})
                data = self._body()
                if data is None:
                    return
                if self._auth_routes(path, data):
                    return
                return self._send(404, {"error": "not found"})
            if not self._guard(post=True):
                return
            data = self._body()
            if data is None:
                return
            if path.startswith("/app/"):
                return self._app_post(path, data)
            m = CONV_RE.match(path)
            if m:
                return self._conv_post(m.group(1), m.group(2), data)
            if path == "/tasks":
                text = self._text(data, "task")
                if text is None:
                    return
                if data.get("idc") is not None and not isinstance(data.get("idc"), bool):
                    return self._send(400, {"error": "'idc' must be true or false"})
                dev = data.get("dev")
                if dev is not None and not isinstance(dev, str):
                    return self._send(400, {"error": "'dev' must be a project name"})
                try:
                    return self._send(201, h.submit(text, data.get("files"), idc=data.get("idc"), dev=dev,
                                                    lang=_lang_arg(data)).snapshot())
                except devmode.DevError as e:
                    return self._send(404, {"error": str(e), "code": e.code})
                except uploads.UploadError as e:
                    return self._send(e.status, {"error": str(e)})
                except Busy as e:
                    return self._send(409, {"error": str(e)})
            m = TASK_RE.match(path)
            if m and m.group(2) == "/messages":
                text = self._text(data, "text")
                if text is None:
                    return
                try:
                    return self._send(202, h.send(m.group(1), text, data.get("files"),
                                                  lang=_lang_arg(data)).snapshot(full=False))
                except uploads.UploadError as e:
                    return self._send(e.status, {"error": str(e)})
                except KeyError:
                    return self._send(404, {"error": "unknown task"})
                except Busy as e:
                    return self._send(409, {"error": str(e)})
            if m and m.group(2) == "/idc":
                if not isinstance(data.get("enabled"), bool):
                    return self._send(400, {"error": "'enabled' (true/false) is required"})
                try:
                    return self._send(200, h.set_task_idc(m.group(1), data["enabled"]).snapshot())
                except KeyError:
                    return self._send(404, {"error": "unknown task"})
                except Busy as e:
                    return self._send(409, {"error": str(e)})
            if path in ("/dev/projects", "/dev/test"):
                try:
                    if path == "/dev/projects":
                        info = h.projects().create(str(data.get("name") or ""), str(data.get("kind") or ""),
                                                   str(data.get("lang") or h.lang))
                        h._audit(None, event="dev_create", project=info["name"], kind=info["kind"])
                        return self._send(201, info)
                    res = h.projects().test(str(data.get("project") or ""))
                    h._audit(None, event="dev_test", project=data.get("project"), ok=res["ok"], runner=res.get("runner"))
                    return self._send(200, res)
                except devmode.DevError as e:
                    code = 404 if e.code in ("no_project",) else (409 if e.code == "exists" else 400)
                    return self._send(code, {"error": str(e), "code": e.code})
            if path == "/files":
                try:
                    return self._send(201, {"saved": h.add_files(data.get("files"))})
                except uploads.UploadError as e:
                    return self._send(e.status, {"error": str(e)})
            if path == "/settings":
                try:
                    return self._send(200, h.update_settings(data))
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
            if m and m.group(2) == "/cancel":
                task = h.cancel(m.group(1))
                if task is None:
                    return self._send(404, {"error": "unknown task"})
                return self._send(202, task.snapshot(full=False))
            m = APPROVAL_RE.match(path)
            if m:
                decision, remember = data.get("decision"), data.get("remember")
                if decision not in ("approve", "deny"):
                    return self._send(400, {"error": "decision must be 'approve' or 'deny'"})
                if remember is not None and (decision != "approve" or remember not in RULE_SCOPES):
                    return self._send(400, {"error": "remember must be 'conversation' or 'session', with approve"})
                ap0 = h.approvals.get(m.group(1))
                if ap0 is None:
                    return self._send(404, {"error": "unknown approval"})
                if remember is not None and ap0.category in NEVER_REMEMBER:
                    return self._send(400, {"error": f"'{ap0.category}' actions are always asked: "
                                                     "they cannot be remembered"})
                try:
                    ap, rule = h.decide(m.group(1), decision == "approve", remember)
                except KeyError:
                    return self._send(404, {"error": "unknown approval"})
                except ValueError as e:
                    return self._send(409, {"error": str(e)})
                return self._send(200, {**ap.as_dict(), "rule": rule})
            if path == "/stop-all":
                return self._send(200, h.stop_all(disable_schedules=bool(data.get("disable_schedules"))))
            m = RULE_RE.match(path)
            if m:
                try:
                    return self._send(200, h.revoke_rule(m.group(1)))
                except KeyError:
                    return self._send(404, {"error": "unknown rule"})
            if path == "/schedules":
                try:
                    return self._send(201, h.add_schedule(data))
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
            if path == "/mcp":
                try:
                    sid = h.mcp.add(data)
                    return self._send(201, {"id": sid, "servers": h.mcp.list_servers()})
                except Exception as e:
                    return self._send(400, {"error": str(e)})
            m = re.match(r"^/mcp/([0-9a-f]+)/delete$", path)
            if m:
                h.mcp.remove(m.group(1))
                return self._send(200, {"ok": True, "servers": h.mcp.list_servers()})
            m = SCHEDULE_RE.match(path)
            if m:
                sid, action = m.group(1), m.group(2)
                try:
                    if action == "/run":
                        t = h.run_schedule(sid, manual=True)
                        return self._send(202, {"task": t.snapshot(full=False) if t else None,
                                                "skipped": t is None})
                    if action == "/delete":
                        return self._send(200, h.delete_schedule(sid))
                    if not isinstance(data.get("enabled"), bool):
                        return self._send(400, {"error": "'enabled' (true/false) is required"})
                    return self._send(200, h.update_schedule(sid, data["enabled"]))
                except KeyError:
                    return self._send(404, {"error": "unknown schedule"})
                except Busy as e:
                    return self._send(409, {"error": str(e)})
            self._send(404, {"error": "not found"})

    return Handler


def make_server(h: Harness, host: str = "127.0.0.1", port: int = 8765,
                token: str | None = None, warn: Callable[[str], None] | None = None,
                remote_mode: bool = False, auth: "remote.Auth | None" = None) -> ThreadingHTTPServer:
    """`remote_mode`: reachable through a tunnel/proxy; a token is mandatory (see agent/remote.py)."""
    warn = warn or (lambda msg: print(msg, file=sys.stderr))
    local = host in LOCAL_HOSTS
    auth = auth or remote.Auth(token or None, remote=remote_mode)
    if (remote_mode or not local) and not auth.required:
        raise ValueError(f"refusing to serve {'in remote mode' if remote_mode else 'on ' + host} without a token: "
                         "set AGENT_HARNESS_TOKEN (or use --remote, which creates one)")
    if not local:
        warn(f"WARNING: harness bound to {host}: reachable from other machines over PLAIN HTTP (no TLS). "
             "The token and your conversations travel unencrypted on that network. Prefer keeping 127.0.0.1 "
             "and a tunnel that adds HTTPS (tailscale serve, cloudflared).")
    srv = ThreadingHTTPServer((host, port), make_handler(h, token or None, local_only=local and not remote_mode,
                                                         auth=auth))
    srv.daemon_threads = True
    return srv
