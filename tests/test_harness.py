import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from agent.harness import Harness, make_server
from agent.llm import LLMReply, MockLLM
from agent.loop import Agent, Budget
from agent.permissions import Permissions
from agent.swarm import SwarmConfig
from agent.tools import default_registry


def wait_for(fn, timeout=10.0, every=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(every)
    raise AssertionError("condition not met in time")


@pytest.fixture
def server(ctx, tmp_path):
    """start(llm_factory, perms=None, timeout=5, token=None) -> (base_url, harness)."""
    started = []

    def start(llm_factory, perms=None, timeout=5.0, token=None, budget=None):
        def factory(task, audit, confirm, cancel, on_event):
            return Agent(llm_factory(), default_registry(enable_web=False, enable_github=False),
                         perms or Permissions(), audit, ctx, budget or Budget(), confirm=confirm,
                         on_event=on_event, swarm=SwarmConfig(), cancel=cancel)
        h = Harness(factory, tmp_path / "state" / "audit.jsonl", approval_timeout=timeout)
        srv = make_server(h, "127.0.0.1", 0, token, warn=lambda m: None)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append((srv, h))
        return f"http://127.0.0.1:{srv.server_address[1]}", h

    yield start
    for srv, h in started:
        h.cancel_all()
        srv.shutdown()
        srv.server_close()


def call(base, method, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(base + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def finished(base, tid):
    def check():
        st, t = call(base, "GET", f"/tasks/{tid}")
        return t if t["status"] in ("done", "stopped", "cancelled", "error") else None
    return wait_for(check)


def pending(base, n=1):
    return wait_for(lambda: (lambda a: a if len(a) >= n else None)(call(base, "GET", "/approvals")[1]["approvals"]))


def test_api_lifecycle_create_poll_result(server):
    base, _ = server(lambda: MockLLM())
    st, t = call(base, "POST", "/tasks", {"task": "what is here?"})
    assert st == 201 and t["status"] in ("queued", "running", "done")
    done = finished(base, t["id"])
    assert done["status"] == "done" and done["stop_reason"] == "final"
    assert "hello.txt" in done["result"]
    assert [a["id"] for a in done["agents"]] == ["root"] and done["usage"]["tool_calls"] == 2
    st, lst = call(base, "GET", "/tasks")
    assert [x["id"] for x in lst["tasks"]] == [t["id"]]
    st, ev = call(base, "GET", f"/tasks/{t['id']}/events")
    tools = [e["tool"] for e in ev["events"] if e["kind"] == "audit"]
    assert tools == ["list_files", "memory_recall"] and ev["next"] == len(ev["events"])
    st, ev2 = call(base, "GET", f"/tasks/{t['id']}/events?since={ev['next']}")
    assert ev2["events"] == []
    assert call(base, "POST", "/tasks", {"task": ""})[0] == 400
    assert call(base, "GET", "/tasks/abcdef")[0] == 404


def test_page_and_guards(server):
    base, _ = server(lambda: MockLLM(), token="s3cret")
    with urllib.request.urlopen(base + "/") as r:
        assert r.status == 200 and b"Pending approvals" in r.read()
    assert call(base, "GET", "/tasks")[0] == 401
    assert call(base, "GET", "/tasks", headers={"Authorization": "Bearer s3cret"})[0] == 200
    auth = {"Authorization": "Bearer s3cret"}
    assert call(base, "POST", "/tasks", {"task": "x"}, {**auth, "Content-Type": "text/plain"})[0] == 415
    assert call(base, "POST", "/tasks", {"task": "x"}, {**auth, "Origin": "http://evil.example"})[0] == 403
    assert call(base, "GET", "/tasks", headers={**auth, "Host": "evil.example"})[0] == 403


def test_non_local_bind_warns(ctx, tmp_path):
    warnings = []
    srv = make_server(Harness(lambda *a: None, tmp_path / "a.jsonl"), "0.0.0.0", 0, None, warn=warnings.append)
    srv.server_close()
    assert warnings and "NOT set" in warnings[0]


def test_approval_queue_approve_and_deny_with_agent_ids(server, ws):
    # root asks to spawn (approved), the child asks to write (denied)
    script = [{"tool": "spawn_agent", "args": {"task": "write x"}},
              {"tool": "write_file", "args": {"path": "x.txt", "content": "hi"}},
              {"content": "child could not write"},
              {"content": "root done"}]
    base, _ = server(lambda: MockLLM(list(script)))
    tid = call(base, "POST", "/tasks", {"task": "go"})[1]["id"]
    ap = pending(base)[0]
    assert (ap["agent"], ap["tool"], ap["category"], ap["task"]) == ("root", "spawn_agent", "delegate", tid)
    assert call(base, "POST", f"/approvals/{ap['id']}", {"decision": "approve"})[1]["status"] == "approved"
    assert call(base, "POST", f"/approvals/{ap['id']}", {"decision": "deny"})[0] == 409
    ap2 = wait_for(lambda: [a for a in call(base, "GET", "/approvals")[1]["approvals"] if a["id"] != ap["id"]])[0]
    assert (ap2["agent"], ap2["tool"]) == ("root.1", "write_file")
    assert call(base, "POST", f"/approvals/{ap2['id']}", {"decision": "deny"})[1]["status"] == "denied"
    done = finished(base, tid)
    assert done["status"] == "done" and done["result"] == "root done"
    assert not (ws / "x.txt").exists()
    tree = {a["id"]: a for a in done["agents"]}
    assert tree["root.1"]["parent"] == "root" and tree["root.1"]["depth"] == 1 and tree["root.1"]["status"] == "done"
    assert call(base, "GET", "/approvals")[1]["approvals"] == []
    statuses = {a["agent"]: a["status"] for a in call(base, "GET", "/approvals?all=1")[1]["approvals"]}
    assert statuses == {"root": "approved", "root.1": "denied"}


def test_approved_write_happens(server, ws):
    base, _ = server(lambda: MockLLM([{"tool": "write_file", "args": {"path": "y.txt", "content": "ok"}},
                                      {"content": "written"}]))
    tid = call(base, "POST", "/tasks", {"task": "w"})[1]["id"]
    call(base, "POST", f"/approvals/{pending(base)[0]['id']}", {"decision": "approve"})
    assert finished(base, tid)["status"] == "done"
    assert (ws / "y.txt").read_text() == "ok"


def test_approval_timeout_counts_as_deny(server, ws, tmp_path):
    base, _ = server(lambda: MockLLM([{"tool": "write_file", "args": {"path": "z.txt", "content": "no"}},
                                      {"content": "gave up"}]), timeout=0.3)
    tid = call(base, "POST", "/tasks", {"task": "w"})[1]["id"]
    done = finished(base, tid)
    assert done["status"] == "done" and not (ws / "z.txt").exists()
    aps = call(base, "GET", "/approvals?all=1")[1]["approvals"]
    assert [a["status"] for a in aps] == ["expired"]
    audit = [json.loads(x) for x in (tmp_path / "state" / "audit.jsonl").read_text().splitlines()]
    assert audit[-1]["tool"] == "write_file" and audit[-1]["decision"] == "deny" and audit[-1]["task_id"] == tid


class EndlessLLM:
    """Never answers: keeps listing files (different args, so no 'no progress' stop)."""
    def __init__(self):
        self.n = 0

    def chat(self, messages, tools=None):
        self.n += 1
        time.sleep(0.02)
        return LLMReply({"role": "assistant", "content": None, "tool_calls": [
            {"id": f"c{self.n}", "type": "function",
             "function": {"name": "list_files", "arguments": json.dumps({"path": ".", "depth": self.n % 3 + 1,
                                                                        "n": self.n})}}]}, 1, 1)


def test_cancel_running_task(server):
    base, _ = server(lambda: EndlessLLM(), budget=Budget(max_steps=100000, max_tool_calls=100000,
                                                         max_tokens=10 ** 9, max_repeats=10 ** 6))
    tid = call(base, "POST", "/tasks", {"task": "forever"})[1]["id"]
    wait_for(lambda: call(base, "GET", f"/tasks/{tid}")[1]["events"] > 5)
    assert call(base, "POST", f"/tasks/{tid}/cancel", {})[0] == 202
    done = finished(base, tid)
    assert done["status"] == "cancelled" and done["stop_reason"] == "cancelled"


def test_cancel_while_waiting_for_approval(server, ws):
    base, _ = server(lambda: MockLLM([{"tool": "write_file", "args": {"path": "c.txt", "content": "x"}},
                                      {"content": "should not be reached"}]), timeout=60)
    tid = call(base, "POST", "/tasks", {"task": "w"})[1]["id"]
    pending(base)
    t0 = time.monotonic()
    call(base, "POST", f"/tasks/{tid}/cancel", {})
    done = finished(base, tid)
    assert time.monotonic() - t0 < 5 and done["status"] == "cancelled" and not (ws / "c.txt").exists()
    assert [a["status"] for a in call(base, "GET", "/approvals?all=1")[1]["approvals"]] == ["cancelled"]
