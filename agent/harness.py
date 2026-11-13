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

import json
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
from . import pwa, qr, remote
from .redact import redact
from . import __version__, export, i18n, schedule, uploads
from .idc import IDC, IDCConfig

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
_I18N_DATA = json.dumps(i18n.ui_strings(), ensure_ascii=False).replace("</", "<\\/")


def render_page(page: str, lang: str | None = None) -> bytes:
    """Insert the EN/FR dictionaries; `?lang=` also sets <html lang> (the page then remembers it)."""
    out = page.replace("/*I18N_DATA*/{}", _I18N_DATA)
    out = out.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n' + pwa.HEAD, 1)
    out = out.replace("width=device-width, initial-scale=1", "width=device-width, initial-scale=1, viewport-fit=cover", 1)
    out = out.replace("</script></body></html>", pwa.REGISTER_JS + "\n</script></body></html>", 1)
    if lang:
        out = out.replace('<html lang="en">', f'<html lang="{i18n.normalize(lang)}">', 1)
    return out.encode("utf-8")
MAX_BODY = 1_000_000
MAX_TASK_CHARS = 20_000
TERMINAL = ("done", "stopped", "cancelled", "error", "interrupted")
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
        self.store = store
        self._lock = threading.Condition(threading.RLock())   # also wakes SSE streams on new events

    # -- persistence
    def record(self) -> dict:
        with self._lock:
            history = self.agent.messages if self.agent is not None else self.history
            return redact({"id": self.id, "task": self.text, "source": self.source, "status": self.status,
                           "created": self.created, "finished": self.finished, "result": self.result,
                           "stop_reason": self.stop_reason, "usage": self.usage, "total": self.total,
                           "agent_usage": self.agent_usage, "agents": list(self.agents.values()),
                           "turns": self.turns, "history": history, "idc": self.idc,
                           "idc_commitments": self.commitments()})

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
        t.idc_saved = [c for c in rec.get("idc_commitments") or [] if isinstance(c, dict)]
        t.agents = {a["id"]: a for a in rec.get("agents") or []} or t.agents
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
            self.turns += 1
            self.status = "queued"
            self.finished = None
            self.result = self.stop_reason = None
            self.agents = {"root": {"id": "root", "parent": None, "depth": 0, "task": text,
                                    "status": "queued", "answer": None}}
        self.cancel.clear()
        self.add_event("user", text=text, turn=self.turns, attachments=attachments or [])
        self.add_event("status", status="queued")
        self.save()

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
                                               "depth": entry.get("child_depth"), "task": entry.get("task"),
                                               "status": "running", "answer": None, "steps": 0,
                                               "max_steps": (entry.get("budget") or {}).get("max_steps"),
                                               "isolated": bool(entry.get("isolated"))}
            elif ev == "child_done" and entry.get("agent") in self.agents:
                a = self.agents[entry["agent"]]
                a["status"] = "done" if entry.get("stop_reason") == "final" else entry.get("stop_reason")
                a["answer"] = entry.get("result")
                if entry.get("steps") is not None:
                    a["steps"] = entry["steps"]
                u = self.agent_usage.setdefault(entry["agent"], {"parent": entry.get("parent"), **_zero()})
                _add(u, entry)

    def on_progress(self, agent: str, steps: Any, max_steps: Any) -> None:
        """One model step done by `agent` (live progress for the swarm graph)."""
        with self._lock:
            a = self.agents.get(agent)
            if a is not None:
                a["steps"], a["max_steps"] = steps, max_steps
        self.add_event("progress", agent=agent, steps=steps, max_steps=max_steps)

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
                        "task": (a.get("task") or "")[:300], "status": a.get("status"), "steps": st,
                        "max_steps": mx or None, "progress": round(prog, 3),
                        "isolated": bool(a.get("isolated")), "answer": (a.get("answer") or "")[:500] or None})
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
        return {"task": self.id, "turn": turn, "status": status, "agents": out, "merges": merges, "files": files,
                "children": len(kids),
                "children_done": bool(kids) and all(a["status"] not in ("running", "queued") for a in kids)}

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


class Harness:
    def __init__(self, agent_factory: AgentFactory, audit_path: str | Path, approval_timeout: float = 300.0,
                 max_tasks: int = 4, workspace: str | Path | None = None,
                 max_upload_mb: float = 20, max_message_mb: float = 50, key_router: Any = None,
                 store: Any = None, backend: dict | None = None, clock: Callable[[], float] = time.time,
                 scheduler_tick: float | None = 1.0, idc_config: IDCConfig | None = None, lang: str = "en"):
        self.factory = agent_factory
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
        self.settings: dict[str, Any] = {"idc": bool(self.idc_config.enabled)}
        self.public_url: str | None = None   # remote mode: the URL a phone should open (tunnel, LAN...)
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

    # -- settings (global) and IDC per conversation
    def get_settings(self) -> dict:
        with self._lock:
            return {**self.settings, "idc_config": self.idc_config.as_dict()}

    def update_settings(self, data: dict) -> dict:
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
    def _audit(self, task: Task | None, **entry: Any) -> dict:
        return (TaskAudit(self.audit_path, task) if task is not None else AuditLog(self.audit_path)).record(**entry)

    def _decode(self, files: Any) -> list[tuple[str, bytes]]:
        decoded = uploads.decode(files, self.upload_limits)
        if decoded and self.workspace is None:
            raise uploads.UploadError(400, "uploads are disabled (no workspace)")
        return decoded

    def _save(self, task: Task, decoded: list[tuple[str, bytes]]) -> list[dict]:
        return uploads.save(self.workspace, task.id, decoded) if decoded else []

    def submit(self, text: str, files: Any = None, source: str = "chat", idc: bool | None = None) -> Task:
        if self.stopping.is_set():
            raise Busy("harness is shutting down")
        decoded = self._decode(files)          # validate everything before creating anything
        task = Task(text, self.store, source)
        with self._lock:
            task.idc = bool(self.settings["idc"] if idc is None else idc)
        saved = self._save(task, decoded)
        with self._lock:
            self._tasks[task.id] = task
        self._start(task, text, saved)
        return task

    def send(self, task_id: str, text: str, files: Any = None) -> Task:
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
                               final=data.get("final"))
            elif kind == "stop":
                task.add_event("stop", agent=data.get("agent", "root"), reason=data.get("reason"))
            elif kind == "idc":
                task.add_event("idc", **{"agent": "root", **data})
            elif kind == "step":
                task.on_progress(data.get("agent", "root"), data.get("steps"), data.get("max_steps"))

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
        return [t.snapshot(full=False) for t in tasks]

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
        keys = self.key_router.status() if self.key_router is not None else None
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

    # -- health
    def health(self, check_backend: bool = False, timeout: float = 3.0) -> dict:
        with self._lock:
            counts: dict[str, int] = {}
            for t in self._tasks.values():
                counts[t.status] = counts.get(t.status, 0) + 1
            n_sched = sum(1 for s in self.schedules.values() if s["enabled"])
        if self.key_router is not None:
            st = self.key_router.status()
            keys = {"mode": "router", "keys": [{f: k.get(f) for f in ("name", "provider", "key", "key_env",
                                                                  "categories", "available", "cooldown_s")}
                                                for k in st.get("keys", [])]}
            urls = sorted({k.base_url for k in self.key_router.entries if getattr(k, "base_url", None)})
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
                "idc": {"default": self.settings["idc"]}}

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
TASK_RE = re.compile(r"^/tasks/([0-9a-f]+)(/events|/cancel|/messages|/stream|/export|/idc|/graph|/file)?$")
APPROVAL_RE = re.compile(r"^/approvals/([0-9a-f]+)$")
RULE_RE = re.compile(r"^/rules/([0-9a-f]+)/revoke$")
SCHEDULE_RE = re.compile(r"^/schedules/([0-9a-f]+)(/run|/delete)?$")
SSE_PING = 15.0


LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")


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

        def _task_file(self, task: Task, rel: str) -> None:
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
                       extra={"Content-Disposition": f'inline; filename="{name}"',
                              "Content-Security-Policy": "sandbox; default-src 'none'"})

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
            if path in ("/", "/chat", "/dashboard", "/connect"):
                page = {"/dashboard": PAGE, "/connect": CONNECT_PAGE}.get(path, CHAT_PAGE)
                if self._host_ok():
                    lang = (q.get("lang") or [None])[0]
                    self._send(200, body=render_page(page, lang), ctype="text/html; charset=utf-8")
                else:
                    self._send(403, {"error": "bad Host header"})
                return
            m = TASK_RE.match(path)
            qtok = (q.get("access_token") or [None])[0] if m and m.group(2) == "/stream" else None
            if not self._guard(post=False, query_token=qtok if qtok and not self.headers.get("Authorization") else None):
                return
            if path == "/tasks":
                return self._send(200, {"tasks": h.list()})
            if path == "/health":
                return self._send(200, h.health(check_backend=(q.get("check") or ["0"])[0] in ("1", "true", "yes")))
            if path == "/usage":
                return self._send(200, h.usage())
            if path == "/rules":
                return self._send(200, {"rules": h.list_rules(), "never_remembered": list(NEVER_REMEMBER)})
            if path == "/schedules":
                return self._send(200, {"schedules": h.list_schedules()})
            if path == "/settings":
                return self._send(200, h.get_settings())
            if path == "/keys":
                if h.key_router is None:
                    return self._send(200, {"mode": "single-key (.env)", "keys": [], "categories": {}})
                return self._send(200, {"mode": "router", **h.key_router.status()})
            if path == "/config":
                lim = h.upload_limits
                return self._send(200, {"uploads": h.workspace is not None,
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
                    return self._task_file(task, (q.get("path") or [""])[0])
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
                return self._send(200, task.snapshot())
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
            if path == "/tasks":
                text = self._text(data, "task")
                if text is None:
                    return
                if data.get("idc") is not None and not isinstance(data.get("idc"), bool):
                    return self._send(400, {"error": "'idc' must be true or false"})
                try:
                    return self._send(201, h.submit(text, data.get("files"), idc=data.get("idc")).snapshot())
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
                    return self._send(202, h.send(m.group(1), text, data.get("files")).snapshot(full=False))
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
