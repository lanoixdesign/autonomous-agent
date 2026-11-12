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

    def start(llm_factory, perms=None, timeout=5.0, token=None, budget=None, swarm=None, max_tasks=4,
              max_upload_mb=20, max_message_mb=50):
        def factory(task, audit, confirm, cancel, on_event):
            return Agent(llm_factory(), default_registry(enable_web=False, enable_github=False),
                         perms or Permissions(), audit, ctx, budget or Budget(), confirm=confirm,
                         on_event=on_event, swarm=swarm or SwarmConfig(), cancel=cancel)
        h = Harness(factory, tmp_path / "state" / "audit.jsonl", approval_timeout=timeout, max_tasks=max_tasks,
                    workspace=ctx.workspace, max_upload_mb=max_upload_mb, max_message_mb=max_message_mb)
        srv = make_server(h, "127.0.0.1", 0, token, warn=lambda m: None)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append((srv, h))
        return f"http://127.0.0.1:{srv.server_address[1]}", h

    yield start
    for srv, h in started:
        h.shutdown()
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
    with urllib.request.urlopen(base + "/dashboard") as r:
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


# ---------------------------------------------------------------- chat page, parallel writers, limits

def test_chat_page_and_approval_popup_roundtrip(server, ws):
    base, _ = server(lambda: MockLLM([{"tool": "write_file", "args": {"path": "p.txt",
                                                                       "content": "token ghp_abcdefghijklmnopqrstuvwx1234"}},
                                      {"content": "first turn done"}, {"content": "second turn done"}]))
    for path in ("/", "/chat"):
        with urllib.request.urlopen(base + path) as r:
            page = r.read()
        assert b"New conversation" in page and b"popups" in page and b"Approve" in page
    tid = call(base, "POST", "/tasks", {"task": "write p"})[1]["id"]
    card = pending(base)[0]
    assert (card["agent"], card["tool"], card["category"], card["task"]) == ("root", "write_file", "write", tid)
    assert "ghp_abc" not in json.dumps(card["args"]) and "REDACTED" in json.dumps(card["args"])
    assert call(base, "POST", f"/tasks/{tid}/messages", {"text": "too early"})[0] == 409   # busy
    assert call(base, "POST", f"/approvals/{card['id']}", {"decision": "approve"})[1]["status"] == "approved"
    assert finished(base, tid)["result"] == "first turn done" and (ws / "p.txt").exists()
    # continue the same conversation: same agent, history kept
    assert call(base, "POST", f"/tasks/{tid}/messages", {"text": "and now?"})[0] == 202
    done = wait_for(lambda: (lambda t: t if t["result"] == "second turn done" else None)(call(base, "GET", f"/tasks/{tid}")[1]))
    assert done["turns"] == 2 and done["status"] == "done"
    users = [e["text"] for e in call(base, "GET", f"/tasks/{tid}/events")[1]["events"] if e["kind"] == "user"]
    assert users == ["write p", "and now?"]


def test_parallel_writing_children_under_harness_with_per_agent_approvals(server, ws, tmp_path):
    from test_isolation import WriterLLM
    llm = WriterLLM(3, conflict=False, delay=0.05)
    base, _ = server(lambda: llm, budget=Budget(max_steps=60, max_tool_calls=60, max_tokens=10 ** 7),
                     swarm=SwarmConfig(max_parallel=3))
    tid = call(base, "POST", "/tasks", {"task": "root"})[1]["id"]
    ap = pending(base)[0]
    assert (ap["agent"], ap["tool"]) == ("root", "spawn_agents")
    call(base, "POST", f"/approvals/{ap['id']}", {"decision": "approve"})
    # the three writers wait for approval AT THE SAME TIME, each card labelled with its own agent id
    cards = wait_for(lambda: (lambda a: a if len(a) == 3 else None)(call(base, "GET", "/approvals")[1]["approvals"]))
    assert sorted(c["agent"] for c in cards) == ["root.1", "root.2", "root.3"]
    assert all(c["tool"] == "write_file" for c in cards)
    for c in cards:   # answered independently: deny the one writing w1.txt
        call(base, "POST", f"/approvals/{c['id']}", {"decision": "deny" if c["args"]["path"] == "w1.txt" else "approve"})
    done = finished(base, tid)
    assert done["status"] == "done" and llm.peak == 3
    assert (ws / "w0.txt").read_text() == "w0" and (ws / "w2.txt").read_text() == "w2" and not (ws / "w1.txt").exists()
    assert sorted(a["id"] for a in done["agents"]) == ["root", "root.1", "root.2", "root.3"]
    events = call(base, "GET", f"/tasks/{tid}/events")[1]["events"]
    merge = [e for e in events if e.get("event") == "merge"][0]
    assert sorted(a["path"] for a in merge["applied"]) == ["w0.txt", "w2.txt"] and merge["conflicts"] == []


class GateLLM:
    """Every call blocks until `gate` is set, then answers. Counts concurrent callers."""
    def __init__(self, gate, stats):
        self.gate, self.stats = gate, stats

    def chat(self, messages, tools=None):
        with self.stats["lock"]:
            self.stats["now"] += 1
            self.stats["peak"] = max(self.stats["peak"], self.stats["now"])
        self.gate.wait(10)
        with self.stats["lock"]:
            self.stats["now"] -= 1
        return LLMReply({"role": "assistant", "content": "ok"}, 1, 1)


def test_max_concurrent_tasks(server):
    gate, stats = threading.Event(), {"lock": threading.Lock(), "now": 0, "peak": 0}
    base, h = server(lambda: GateLLM(gate, stats), max_tasks=2)
    ids = [call(base, "POST", "/tasks", {"task": f"t{i}"})[1]["id"] for i in range(4)]
    wait_for(lambda: stats["now"] == 2)
    time.sleep(0.3)
    statuses = sorted(call(base, "GET", f"/tasks/{i}")[1]["status"] for i in ids)
    assert statuses == ["queued", "queued", "running", "running"] and h.running() == 2
    # a queued task can be cancelled before it starts
    queued = [i for i in ids if call(base, "GET", f"/tasks/{i}")[1]["status"] == "queued"]
    call(base, "POST", f"/tasks/{queued[0]}/cancel", {})
    assert finished(base, queued[0])["status"] == "cancelled"
    gate.set()
    assert sorted(finished(base, i)["status"] for i in ids) == ["cancelled", "done", "done", "done"]
    assert stats["peak"] == 2


# ---------------------------------------------------------------- attachments

import base64  # noqa: E402


def b64(data):
    return base64.b64encode(data if isinstance(data, bytes) else data.encode()).decode()


class ReadAttachmentLLM:
    """Reads the first attached path announced in the user message, then answers with what it read."""
    def __init__(self):
        self.seen = []

    def chat(self, messages, tools=None):
        user = [m for m in messages if m["role"] == "user"][-1]["content"]
        self.seen.append(user)
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        if not tool_msgs or messages[-1]["role"] == "user":
            path = [ln[2:].split(" (")[0] for ln in user.splitlines() if ln.startswith("- uploads/")][0]
            return LLMReply({"role": "assistant", "content": None, "tool_calls": [
                {"id": "r", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": path})}}]}, 1, 1)
        return LLMReply({"role": "assistant", "content": "read: " + tool_msgs[-1]["content"]}, 1, 1)


def test_upload_roundtrip_and_agent_gets_paths(server, ws, tmp_path):
    llm = ReadAttachmentLLM()
    base, _ = server(lambda: llm)
    png = bytes(range(256)) * 4
    st, t = call(base, "POST", "/tasks", {"task": "summarise", "files": [
        {"name": "notes.md", "content_b64": b64("# Notes\nbuy milk\n")},
        {"name": "pic.png", "content_b64": b64(png)}]})
    assert st == 201
    tid = t["id"]
    done = finished(base, tid)
    assert (ws / "uploads" / tid / "notes.md").read_text() == "# Notes\nbuy milk\n"
    assert (ws / "uploads" / tid / "pic.png").read_bytes() == png
    # the agent received the workspace-relative paths (+ the small text file inlined) and read it
    msg = llm.seen[0]
    assert f"- uploads/{tid}/notes.md (17 bytes, text)" in msg and f"- uploads/{tid}/pic.png (1024 bytes, binary)" in msg
    assert "buy milk" in msg and "buy milk" in done["result"]
    ev = call(base, "GET", f"/tasks/{tid}/events")[1]["events"]
    user = [e for e in ev if e["kind"] == "user"][0]
    assert user["text"] == "summarise" and [a["name"] for a in user["attachments"]] == ["notes.md", "pic.png"]
    audit = [json.loads(x) for x in (tmp_path / "state" / "audit.jsonl").read_text().splitlines()]
    ups = [l for l in audit if l.get("event") == "upload"]
    assert [u["path"] for u in ups] == [f"uploads/{tid}/notes.md", f"uploads/{tid}/pic.png"]
    assert ups[0]["bytes"] == 17 and len(ups[0]["sha256"]) == 64 and ups[0]["task_id"] == tid
    # a follow-up message with a file (and no text) goes to the same conversation folder
    st, _ = call(base, "POST", f"/tasks/{tid}/messages", {"files": [{"name": "notes.md", "content_b64": b64("v2")}]})
    assert st == 202
    wait_for(lambda: call(base, "GET", f"/tasks/{tid}")[1]["turns"] == 2 and finished(base, tid))
    assert (ws / "uploads" / tid / "notes-1.md").read_text() == "v2"         # never overwrites
    assert "Please look at the attached file(s)." in llm.seen[-1]


def test_upload_names_are_sanitized(server, ws, tmp_path):
    base, _ = server(lambda: MockLLM([{"content": "ok"}]))
    names = ["../../evil.txt", "/etc/passwd", "..\\..\\win.ini", ".env", "a/b/c.txt", "..", "x\x00y.txt"]
    st, t = call(base, "POST", "/tasks", {"task": "t", "files": [{"name": n, "content_b64": b64("x")} for n in names]})
    assert st == 201
    finished(base, t["id"])
    d = ws / "uploads" / t["id"]
    assert sorted(p.name for p in d.iterdir()) == sorted(
        ["evil.txt", "passwd", "win.ini", "env", "c.txt", "file", "xy.txt"])
    assert not (tmp_path / "evil.txt").exists() and not (ws / "evil.txt").exists()
    assert (ws / ".env").read_text() == "SECRET=1\n"                           # untouched


def test_upload_refuses_symlinked_uploads_dir(server, ws, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / "uploads").symlink_to(outside, target_is_directory=True)
    base, _ = server(lambda: MockLLM([{"content": "ok"}]))
    st, r = call(base, "POST", "/tasks", {"task": "t", "files": [{"name": "a.txt", "content_b64": b64("x")}]})
    assert st == 400 and "symlink" in r["error"] and list(outside.iterdir()) == []
    assert call(base, "GET", "/tasks")[1]["tasks"] == []


def test_upload_size_limits_413(server, ws):
    base, _ = server(lambda: MockLLM([{"content": "ok"}]), max_upload_mb=0.001, max_message_mb=0.0015)
    big = "x" * 1100                                    # > 1048 bytes
    st, r = call(base, "POST", "/tasks", {"task": "t", "files": [{"name": "big.txt", "content_b64": b64(big)}]})
    assert st == 413 and "limit" in r["error"]
    two = [{"name": f"f{i}.txt", "content_b64": b64("y" * 900)} for i in range(2)]   # 1800 > 1572 per message
    st, r = call(base, "POST", "/tasks", {"task": "t", "files": two})
    assert st == 413 and "per-message" in r["error"]
    assert call(base, "POST", "/tasks", {"task": "t", "files": [{"name": "a", "content_b64": "%%%"}]})[0] == 400
    assert not (ws / "uploads").exists() and call(base, "GET", "/tasks")[1]["tasks"] == []
    assert call(base, "GET", "/config")[1]["max_upload_bytes"] == 1048


def test_upload_requires_token_when_set(server, ws):
    base, _ = server(lambda: MockLLM([{"content": "ok"}]), token="s3cret")
    body = {"task": "t", "files": [{"name": "a.txt", "content_b64": b64("x")}]}
    assert call(base, "POST", "/tasks", body)[0] == 401
    assert call(base, "POST", "/tasks", body, {"Authorization": "Bearer s3cret", "Origin": "http://evil.example"})[0] == 403
    assert not (ws / "uploads").exists()
    st, t = call(base, "POST", "/tasks", body, {"Authorization": "Bearer s3cret"})
    assert st == 201 and (ws / "uploads" / t["id"] / "a.txt").exists()


def test_chat_page_has_attach_ui(server):
    base, _ = server(lambda: MockLLM())
    with urllib.request.urlopen(base + "/") as r:
        page = r.read().decode()
    for needle in ('id="attach"', 'type="file" multiple', 'id="chips"', '"drop"', "content_b64", "Drop files to attach"):
        assert needle in page
