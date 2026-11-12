"""Local harness: `python -m agent serve`. Runs agent tasks in background threads behind a small
JSON API (stdlib http.server) and a one-page UI, with an approval queue instead of terminal prompts.

API (JSON):
  POST /tasks                 {"task": "..."}            -> 201 {"id": ...}   (a task is a conversation)
  POST /tasks/{id}/messages   {"text": "..."}            -> continue the conversation (409 if busy)
      both accept "files": [{"name": ..., "content_b64": ...}] -> saved in <workspace>/uploads/<id>/
  GET  /config                upload limits
  GET  /tasks                                            -> {"tasks": [...]}
  GET  /tasks/{id}            task + agent tree (root, root.1, ...) + status + result
  GET  /tasks/{id}/events?since=N                        -> {"events": [...], "next": M}  (polling)
  POST /tasks/{id}/cancel
  GET  /approvals[?all=1]     pending (or all) approval requests, each with the requesting agent id
  POST /approvals/{id}        {"decision": "approve" | "deny"}
  GET  /                      chat page (approvals pop up as cards)
  GET  /dashboard             compact dashboard page

At most `max_tasks` turns run at once (default 4); the others wait in status "queued".

Approvals: each `ask` decision becomes a pending approval; the agent thread waits until someone
approves/denies it, the task is cancelled, or `approval_timeout` seconds pass. No answer = deny.

Security: binds 127.0.0.1 by default. If AGENT_HARNESS_TOKEN is set, every API call needs
`Authorization: Bearer <token>`. POSTs must be `application/json` and same-origin, and the Host header
is checked when bound to localhost (protects against other web pages and DNS rebinding). This is NOT
an authenticated multi-user server: do not expose it to a network you do not trust.
"""
from __future__ import annotations

import hmac
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
from .redact import redact
from . import uploads

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
MAX_BODY = 1_000_000
MAX_TASK_CHARS = 20_000
TERMINAL = ("done", "stopped", "cancelled", "error")


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
                "status": self.status, "created": self.created, "decided": self.decided}


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

    def list(self, pending_only: bool = True) -> list[dict]:
        with self._lock:
            return [a.as_dict() for a in self._items.values() if a.status == "pending" or not pending_only]


class HarnessConfirm:
    """`confirm` callback for agents run by the harness; `with_agent` receives the asking agent id.
    `concurrent = True`: several agents may wait for approval at once (parallel sub-agents)."""

    concurrent = True

    def __init__(self, queue: ApprovalQueue, task: "Task"):
        self.queue, self.task = queue, task

    def __call__(self, tool: str, category: str, args: dict, reason: str) -> bool:
        return self.with_agent("root", tool, category, args, reason)

    def with_agent(self, agent: str, tool: str, category: str, args: dict, reason: str) -> bool:
        def notify(ap: Approval) -> None:
            self.task.add_event("approval", agent=ap.agent, approval=ap.id, tool=ap.tool, status=ap.status)
        return self.queue.request(self.task.id, agent, tool, category, args, reason, self.task.cancel, notify)


# ---------------------------------------------------------------------------- tasks
class Task:
    def __init__(self, text: str):
        self.id = uuid.uuid4().hex[:10]
        self.text = text
        self.status = "queued"
        self.created, self.finished = _now(), None
        self.result: str | None = None
        self.stop_reason: str | None = None
        self.usage: dict = {}
        self.cancel = threading.Event()
        self.agents: dict[str, dict] = {"root": {"id": "root", "parent": None, "depth": 0, "task": text,
                                                 "status": "queued", "answer": None}}
        self.events: list[dict] = []
        self.turns = 0
        self.agent: Any = None          # created on the first turn, kept for the conversation
        self._lock = threading.Lock()

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

    def add_event(self, kind: str, **data: Any) -> None:
        with self._lock:
            self.events.append({"seq": len(self.events), "ts": _now(), "kind": kind, **data})

    def on_audit(self, entry: dict) -> None:
        self.add_event("audit", **{k: v for k, v in entry.items() if k != "task_id"})
        ev = entry.get("event")
        with self._lock:
            if ev == "spawn":
                self.agents[entry["child"]] = {"id": entry["child"], "parent": entry.get("agent"),
                                               "depth": entry.get("child_depth"), "task": entry.get("task"),
                                               "status": "running", "answer": None}
            elif ev == "child_done" and entry.get("agent") in self.agents:
                a = self.agents[entry["agent"]]
                a["status"] = "done" if entry.get("stop_reason") == "final" else entry.get("stop_reason")
                a["answer"] = entry.get("result")

    def set_status(self, status: str) -> None:
        with self._lock:
            self.status = status
            self.agents["root"]["status"] = status
            if status in TERMINAL:
                self.finished = _now()

    def snapshot(self, full: bool = True) -> dict:
        with self._lock:
            d = {"id": self.id, "task": self.text, "status": self.status, "created": self.created,
                 "finished": self.finished, "stop_reason": self.stop_reason, "result": self.result,
                 "turns": self.turns}
            if full:
                d["usage"] = dict(self.usage)
                d["agents"] = [dict(a) for a in self.agents.values()]
                d["events"] = len(self.events)
            return d

    def events_since(self, since: int) -> tuple[list[dict], int]:
        with self._lock:
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
                 max_upload_mb: float = 20, max_message_mb: float = 50):
        self.factory = agent_factory
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
        self._lock = threading.Lock()

    def _decode(self, files: Any) -> list[tuple[str, bytes]]:
        decoded = uploads.decode(files, self.upload_limits)
        if decoded and self.workspace is None:
            raise uploads.UploadError(400, "uploads are disabled (no workspace)")
        return decoded

    def _save(self, task: Task, decoded: list[tuple[str, bytes]]) -> list[dict]:
        return uploads.save(self.workspace, task.id, decoded) if decoded else []

    def submit(self, text: str, files: Any = None) -> Task:
        decoded = self._decode(files)          # validate everything before creating anything
        task = Task(text)
        saved = self._save(task, decoded)
        with self._lock:
            self._tasks[task.id] = task
        self._start(task, text, saved)
        return task

    def send(self, task_id: str, text: str, files: Any = None) -> Task:
        """Continue a conversation with a new user message (same agent, history kept)."""
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

        # wait for a free slot (max_tasks), unless cancelled while queued
        while not self._slots.acquire(timeout=0.1):
            if task.cancel.is_set():
                task.result, task.stop_reason = "Cancelled while queued.", "cancelled"
                task.set_status("cancelled")
                task.add_event("status", status="cancelled")
                return
        try:
            task.set_status("running")
            task.add_event("status", status="running")
            try:
                if task.agent is None:
                    task.agent = self.factory(task, TaskAudit(self.audit_path, task),
                                              HarnessConfirm(self.approvals, task), task.cancel, on_event)
                res = task.agent.run(text)
                task.result, task.stop_reason = res.answer, res.stop_reason
                task.usage = {"steps": res.steps, "tool_calls": res.tool_calls, "tokens": res.tokens}
                status = {"final": "done", "cancelled": "cancelled"}.get(res.stop_reason, "stopped")
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

    def shutdown(self, wait: float = 10.0) -> None:
        """Cancel everything and give running turns a moment to stop (temp workspace copies are removed)."""
        self.cancel_all()
        end = time.monotonic() + wait
        while time.monotonic() < end:
            with self._lock:
                busy = any(t.status in ("running", "cancelling") for t in self._tasks.values())
            if not busy:
                return
            time.sleep(0.05)


# ---------------------------------------------------------------------------- HTTP
TASK_RE = re.compile(r"^/tasks/([0-9a-f]+)(/events|/cancel|/messages)?$")
APPROVAL_RE = re.compile(r"^/approvals/([0-9a-f]+)$")


def make_handler(h: Harness, token: str | None, local_only: bool):
    class Handler(BaseHTTPRequestHandler):
        server_version = "autonomous-agent-harness"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # quiet
            pass

        def _send(self, code: int, obj: Any = None, body: bytes | None = None,
                  ctype: str = "application/json; charset=utf-8") -> None:
            if body is None:
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self) -> bool:
            if not local_only:
                return True
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            return host in LOCAL_HOSTS

        def _auth_ok(self) -> bool:
            if not token:
                return True
            return hmac.compare_digest(self.headers.get("Authorization", "").encode(), f"Bearer {token}".encode())

        def _guard(self, post: bool) -> bool:
            if not self._host_ok():
                self._send(403, {"error": "bad Host header"})
                return False
            if post:
                origin = self.headers.get("Origin")
                if origin and urlparse(origin).netloc != self.headers.get("Host"):
                    self._send(403, {"error": "cross-origin request refused"})
                    return False
                if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                    self._send(415, {"error": "Content-Type must be application/json"})
                    return False
            if not self._auth_ok():
                self._send(401, {"error": "missing or bad bearer token (AGENT_HARNESS_TOKEN)"})
                return False
            return True

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

        def do_GET(self) -> None:  # noqa: N802
            u = urlparse(self.path)
            path, q = u.path.rstrip("/") or "/", parse_qs(u.query)
            if path in ("/", "/chat", "/dashboard"):
                page = PAGE if path == "/dashboard" else CHAT_PAGE
                if self._host_ok():
                    self._send(200, body=page.encode("utf-8"), ctype="text/html; charset=utf-8")
                else:
                    self._send(403, {"error": "bad Host header"})
                return
            if not self._guard(post=False):
                return
            if path == "/tasks":
                return self._send(200, {"tasks": h.list()})
            if path == "/config":
                lim = h.upload_limits
                return self._send(200, {"uploads": h.workspace is not None,
                                        "max_upload_bytes": lim.max_file_bytes,
                                        "max_message_bytes": lim.max_message_bytes})
            if path == "/approvals":
                return self._send(200, {"approvals": h.approvals.list(pending_only="all" not in q)})
            m = TASK_RE.match(path)
            if m and m.group(2) in (None, "/events"):
                task = h.get(m.group(1))
                if task is None:
                    return self._send(404, {"error": "unknown task"})
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
            if not self._guard(post=True):
                return
            data = self._body()
            if data is None:
                return
            if path == "/tasks":
                text = self._text(data, "task")
                if text is None:
                    return
                try:
                    return self._send(201, h.submit(text, data.get("files")).snapshot())
                except uploads.UploadError as e:
                    return self._send(e.status, {"error": str(e)})
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
            if m and m.group(2) == "/cancel":
                task = h.cancel(m.group(1))
                if task is None:
                    return self._send(404, {"error": "unknown task"})
                return self._send(202, task.snapshot(full=False))
            m = APPROVAL_RE.match(path)
            if m:
                decision = data.get("decision")
                if decision not in ("approve", "deny"):
                    return self._send(400, {"error": "decision must be 'approve' or 'deny'"})
                try:
                    ap = h.approvals.decide(m.group(1), decision == "approve")
                except KeyError:
                    return self._send(404, {"error": "unknown approval"})
                except ValueError as e:
                    return self._send(409, {"error": str(e)})
                return self._send(200, ap.as_dict())
            self._send(404, {"error": "not found"})

    return Handler


def make_server(h: Harness, host: str = "127.0.0.1", port: int = 8765,
                token: str | None = None, warn: Callable[[str], None] | None = None) -> ThreadingHTTPServer:
    warn = warn or (lambda msg: print(msg, file=sys.stderr))
    local = host in LOCAL_HOSTS
    if not local:
        warn(f"WARNING: harness bound to {host}, reachable from other machines. Anyone who can reach it "
             "can run your agent" + ("." if token else " — and AGENT_HARNESS_TOKEN is NOT set."))
    srv = ThreadingHTTPServer((host, port), make_handler(h, token or None, local_only=local))
    srv.daemon_threads = True
    return srv
