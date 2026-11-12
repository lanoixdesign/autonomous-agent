"""Harness improvements: persistence, SSE, stop-all, remembered rules, usage, export, schedules, /health."""
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent.harness import Harness, HarnessConfirm, Task, make_server
from agent.keys import KeyEntry, KeyRouter
from agent.llm import LLMReply, MockLLM, RoutedLLM
from agent.loop import Agent, Budget
from agent.permissions import Permissions
from agent.redact import redact
from agent.store import Store
from agent.swarm import SwarmConfig
from agent.tools import default_registry
from agent import schedule

from test_harness import EndlessLLM, call, finished, pending, wait_for


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def make(ctx, tmp_path):
    """make(llm_factory, **harness_kwargs) -> (base, harness); `db=True` adds a Store in tmp_path."""
    started = []

    def _make(llm_factory, token=None, budget=None, db=False, serve=True, perms=None, **kw):
        def factory(task, audit, confirm, cancel, on_event):
            return Agent(llm_factory(), default_registry(enable_web=False, enable_github=False),
                         perms or Permissions(), audit, ctx, budget or Budget(), confirm=confirm,
                         on_event=on_event, swarm=SwarmConfig(), cancel=cancel)
        if db:
            kw["store"] = Store(tmp_path / "state" / "harness.sqlite3")
        kw.setdefault("scheduler_tick", None)
        kw.setdefault("approval_timeout", 10)
        h = Harness(factory, tmp_path / "state" / "audit.jsonl", workspace=ctx.workspace, **kw)
        base = None
        if serve:
            srv = make_server(h, "127.0.0.1", 0, token, warn=lambda m: None)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            started.append((srv, h))
        else:
            started.append((None, h))
        return base, h

    yield _make
    for srv, h in started:
        h.shutdown(wait=5)
        if srv is not None:
            srv.shutdown()
            srv.server_close()


def audit_lines(tmp_path):
    return [json.loads(x) for x in (tmp_path / "state" / "audit.jsonl").read_text().splitlines()]


def write_script(*names, final="ok"):
    s = [{"tool": "write_file", "args": {"path": n, "content": n}} for n in names]
    return s + [{"content": final}]


# ---------------------------------------------------------------- 1. persistence
class RecordingLLM(MockLLM):
    seen: list = []

    def chat(self, messages, tools=None):
        RecordingLLM.seen.append([m.get("content") for m in messages])
        return super().chat(messages, tools)


def test_persistence_restores_conversations_and_marks_interrupted(make, tmp_path, ws):
    base, h1 = make(lambda: RecordingLLM([{"content": "first answer"}, {"content": "second answer"}]), db=True)
    done_id = call(base, "POST", "/tasks", {"task": "remember the word banana"})[1]["id"]
    finished(base, done_id)
    # a turn persisted as "running" when the process died (no clean shutdown)
    st = Store(tmp_path / "state" / "harness.sqlite3")
    busy = Task("long job", st)
    busy.new_turn("long job")
    busy.set_status("running")
    busy.add_event("status", status="running")

    # restart: a new Harness on the same database
    _, h2 = make(lambda: RecordingLLM([{"content": "second answer"}]), db=True, serve=False)
    t1, t2 = h2.get(done_id), h2.get(busy.id)
    assert t1.status == "done" and t1.result == "first answer" and t1.turns == 1
    assert [e["kind"] for e in t1.events][:2] == ["user", "status"] and t1.events[-1]["status"] == "done"
    assert t2.status == "interrupted" and t2.stop_reason == "interrupted"
    assert t2.events[-1] == {**t2.events[-1], "kind": "status", "status": "interrupted"}
    # continuing the restored conversation: the agent gets the earlier messages back
    RecordingLLM.seen.clear()
    h2.send(done_id, "what was the word?")
    wait_for(lambda: h2.get(done_id).status == "done")
    contents = RecordingLLM.seen[-1]
    assert "remember the word banana" in contents and "first answer" in contents
    assert h2.get(done_id).turns == 2 and h2.get(done_id).total["steps"] == 2
    # an interrupted conversation can be continued too
    assert h2.send(busy.id, "go on").status in ("queued", "running", "done")
    wait_for(lambda: h2.get(busy.id).status == "done")


def test_store_roundtrip_and_session_rules_not_restored(tmp_path):
    s = Store(tmp_path / "x.sqlite3")
    s.put("rules", "r1", {"id": "r1", "scope": "session", "task_id": "t"})
    s.put("schedules", "s1", {"id": "s1", "n": 1})
    s.add_event("t", 0, {"seq": 0, "kind": "user"})
    s.add_event("t", 1, {"seq": 1, "kind": "status"})
    assert [e["seq"] for e in s.events("t")] == [0, 1]
    assert s.all("schedules") == [{"id": "s1", "n": 1}]
    h = Harness(lambda *a: None, tmp_path / "a.jsonl", store=s, scheduler_tick=None)
    assert h.rules == {} and s.all("rules") == [] and "s1" in h.schedules
    assert oct((tmp_path / "x.sqlite3").stat().st_mode & 0o777) == "0o600"


# ---------------------------------------------------------------- 2. SSE
def read_sse(url, headers=None, timeout=10):
    req = urllib.request.Request(url, headers=headers or {})
    events = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        assert r.headers["Content-Type"].startswith("text/event-stream")
        for raw in r:
            line = raw.decode().rstrip("\n")
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def test_sse_stream_pushes_events_and_resumes(make):
    base, h = make(lambda: MockLLM())
    tid = call(base, "POST", "/tasks", {"task": "what is here?"})[1]["id"]
    got = read_sse(f"{base}/tasks/{tid}/stream?once=1")
    assert [e["seq"] for e in got] == list(range(len(got)))
    assert got[-1]["kind"] == "status" and got[-1]["status"] == "done"
    polled = call(base, "GET", f"/tasks/{tid}/events")[1]["events"]
    assert got == polled
    # resume after an id (Last-Event-ID, as EventSource does on reconnect) and via ?since=
    again = read_sse(f"{base}/tasks/{tid}/stream?once=1", {"Last-Event-ID": str(len(got) - 3)})
    assert [e["seq"] for e in again] == [len(got) - 2, len(got) - 1]
    assert [e["seq"] for e in read_sse(f"{base}/tasks/{tid}/stream?once=1&since={len(got) - 1}")] == [len(got) - 1]
    assert call(base, "GET", "/tasks/0000/stream")[0] == 404


def test_sse_live_while_running_and_token(make, ws):
    base, h = make(lambda: MockLLM(write_script("s.txt")), token="tok3n")
    auth = {"Authorization": "Bearer tok3n"}
    tid = call(base, "POST", "/tasks", {"task": "w"}, auth)[1]["id"]
    seen = []

    def reader():
        seen.extend(read_sse(f"{base}/tasks/{tid}/stream?once=1&access_token=tok3n"))
    th = threading.Thread(target=reader)
    th.start()
    ap = wait_for(lambda: call(base, "GET", "/approvals", headers=auth)[1]["approvals"])[0]
    call(base, "POST", f"/approvals/{ap['id']}", {"decision": "approve"}, auth)
    th.join(10)
    kinds = [(e["kind"], e.get("status")) for e in seen]
    assert ("approval", "pending") in kinds and ("approval", "approved") in kinds and kinds[-1] == ("status", "done")
    with pytest.raises(urllib.error.HTTPError) as e:
        read_sse(f"{base}/tasks/{tid}/stream?once=1&access_token=wrong")
    assert e.value.code == 401
    with pytest.raises(urllib.error.HTTPError):
        read_sse(f"{base}/tasks/{tid}/stream?once=1")
    # the query token is only accepted on /stream
    assert call(base, "GET", "/tasks?access_token=tok3n")[0] == 401


def test_chat_page_uses_eventsource_with_polling_fallback(make):
    base, _ = make(lambda: MockLLM())
    page = urllib.request.urlopen(base + "/").read().decode()
    assert "new EventSource(" in page and "/events?since=" in page and "polling" in page
    assert 'id="stopall"' in page and "remember" in page and "/export?format=" in page


# ---------------------------------------------------------------- 3. emergency stop
def test_stop_all_cancels_everything_and_denies_approvals(make, ws, tmp_path):
    llms = iter([MockLLM(write_script("a.txt")), MockLLM(write_script("b.txt")), EndlessLLM()])
    base, h = make(lambda: next(llms), budget=Budget(max_steps=10 ** 5, max_tool_calls=10 ** 5, max_tokens=10 ** 9,
                                                     max_repeats=10 ** 6), approval_timeout=60)
    ids = [call(base, "POST", "/tasks", {"task": f"t{i}"})[1]["id"] for i in range(3)]
    pending(base, 2)
    sid = call(base, "POST", "/schedules", {"prompt": "nightly", "daily_at": "03:00"})[1]["id"]
    st, r = call(base, "POST", "/stop-all", {"disable_schedules": True})
    assert st == 200 and sorted(r["cancelled"]) == sorted(ids) and len(r["approvals_denied"]) == 2
    assert r["schedules_paused"] == [sid]
    for tid in ids:
        assert finished(base, tid)["status"] == "cancelled"
    assert {a["status"] for a in call(base, "GET", "/approvals?all=1")[1]["approvals"]} == {"denied"}
    assert not (ws / "a.txt").exists() and not (ws / "b.txt").exists()
    assert call(base, "GET", "/schedules")[1]["schedules"][0]["enabled"] is False
    stop = [a for a in audit_lines(tmp_path) if a.get("event") == "stop_all"]
    assert len(stop) == 1 and sorted(stop[0]["tasks"]) == sorted(ids)
    # nothing to stop: still fine
    assert call(base, "POST", "/stop-all", {})[1]["cancelled"] == []


# ---------------------------------------------------------------- 4. remembered approval rules
def test_rule_conversation_scope_then_revoke(make, ws, tmp_path):
    base, h = make(lambda: MockLLM(write_script("r1.txt", "r2.txt", final="t1") + write_script("r3.txt", final="t2")))
    tid = call(base, "POST", "/tasks", {"task": "write"})[1]["id"]
    ap = pending(base)[0]
    assert ap["rememberable"] is True
    st, out = call(base, "POST", f"/approvals/{ap['id']}", {"decision": "approve", "remember": "conversation"})
    assert st == 200 and out["rule"]["scope"] == "conversation" and out["rule"]["tool"] == "write_file"
    finished(base, tid)
    assert (ws / "r1.txt").exists() and (ws / "r2.txt").exists()       # 2nd write: no prompt
    assert len(call(base, "GET", "/approvals?all=1")[1]["approvals"]) == 1
    rules = call(base, "GET", "/rules")[1]
    assert rules["never_remembered"] == ["send", "spend"] and rules["rules"][0]["uses"] == 1
    events = call(base, "GET", f"/tasks/{tid}/events")[1]["events"]
    assert any(e["kind"] == "approval" and e["status"] == "auto-approved" for e in events)
    # revoke: the same conversation asks again
    assert call(base, "POST", f"/rules/{out['rule']['id']}/revoke", {})[0] == 200
    assert call(base, "POST", f"/rules/{out['rule']['id']}/revoke", {})[0] == 404
    call(base, "POST", f"/tasks/{tid}/messages", {"text": "again"})
    ap2 = pending(base)[0]
    call(base, "POST", f"/approvals/{ap2['id']}", {"decision": "deny"})
    finished(base, tid)
    assert not (ws / "r3.txt").exists()
    evs = [a["event"] for a in audit_lines(tmp_path) if a.get("event", "").startswith("rule_")]
    assert evs == ["rule_created", "rule_applied", "rule_revoked"]


def test_rule_scopes_and_send_spend_never_remembered(make, ws, tmp_path):
    base, h = make(lambda: MockLLM(write_script("x.txt")))
    t1 = call(base, "POST", "/tasks", {"task": "one"})[1]["id"]
    ap = pending(base)[0]
    call(base, "POST", f"/approvals/{ap['id']}", {"decision": "approve", "remember": "conversation"})
    finished(base, t1)
    t2 = call(base, "POST", "/tasks", {"task": "two"})[1]["id"]     # other conversation: asks again
    ap2 = pending(base)[0]
    assert ap2["task"] == t2
    assert call(base, "POST", f"/approvals/{ap2['id']}", {"decision": "deny", "remember": "session"})[0] == 400
    assert call(base, "POST", f"/approvals/{ap2['id']}", {"decision": "approve", "remember": "forever"})[0] == 400
    call(base, "POST", f"/approvals/{ap2['id']}", {"decision": "approve", "remember": "session"})
    finished(base, t2)
    t3 = call(base, "POST", "/tasks", {"task": "three"})[1]["id"]   # session rule: no prompt at all
    assert finished(base, t3)["status"] == "done" and (ws / "x.txt").exists()
    assert len(call(base, "GET", "/approvals?all=1")[1]["approvals"]) == 2

    # send / spend: the card cannot remember, the API refuses, and a rule would never match anyway
    task = h.get(t3)
    results = []
    for cat in ("send", "spend"):
        th = threading.Thread(target=lambda c=cat: results.append(
            HarnessConfirm(h.approvals, task, h).with_agent("root", "pay", c, {"amount": 5}, "test")))
        th.start()
        ap = wait_for(lambda: [a for a in call(base, "GET", "/approvals")[1]["approvals"] if a["tool"] == "pay"])[0]
        assert ap["rememberable"] is False
        st, err = call(base, "POST", f"/approvals/{ap['id']}", {"decision": "approve", "remember": "session"})
        assert st == 400 and "always asked" in err["error"]
        call(base, "POST", f"/approvals/{ap['id']}", {"decision": "deny"})
        th.join(5)
        with pytest.raises(ValueError):
            h.add_rule("session", "pay", cat, task)
        h.rules["forced"] = {"id": "forced", "scope": "session", "tool": "pay", "category": cat, "task_id": t3}
        assert h.match_rule(t3, "pay", cat) is None
        del h.rules["forced"]
    assert results == [False, False]


# ---------------------------------------------------------------- 5. usage
class CostLLM(MockLLM):
    def chat(self, messages, tools=None):
        r = super().chat(messages, tools)
        r.prompt_tokens, r.completion_tokens, r.cost = 100, 10, 0.001
        return r


def test_usage_per_conversation_and_agent(make):
    script = [{"tool": "spawn_agent", "args": {"task": "look"}}, {"content": "child says hi"},
              {"content": "root done"}, {"content": "turn 2"}]
    base, h = make(lambda: CostLLM(list(script)), perms=Permissions.from_dict({"defaults": {"delegate": "allow"}}))
    tid = call(base, "POST", "/tasks", {"task": "go"})[1]["id"]
    finished(base, tid)
    call(base, "POST", f"/tasks/{tid}/messages", {"text": "more"})
    finished(base, tid)
    u = call(base, "GET", "/usage")[1]
    conv = u["conversations"][0]
    agents = {a["id"]: a for a in conv["agents"]}
    assert set(agents) == {"root", "root.1"}
    assert agents["root.1"]["steps"] == 1 and agents["root.1"]["tokens"] == 110
    assert agents["root"]["steps"] == 4 and agents["root"]["tokens"] == 440      # inclusive, 2 turns
    assert agents["root"]["own"]["steps"] == 3 and agents["root"]["own"]["tokens"] == 330
    assert abs(agents["root"]["cost"] - 0.004) < 1e-9 and abs(agents["root"]["own"]["cost"] - 0.003) < 1e-9
    assert conv["total"]["steps"] == 4 and conv["turns"] == 2 and u["total"]["tokens"] == 440
    assert u["keys"] is None
    # tokens counters stay readable in the audit (redaction keeps numeric *tokens fields)
    assert redact({"tokens": 5, "max_tokens": 9, "api_token": "abcdefgh12", "token": 3}) == \
        {"tokens": 5, "max_tokens": 9, "api_token": "***REDACTED***", "token": "***REDACTED***"}


def test_routed_llm_reports_cost_and_usage_shows_key_quotas(make, monkeypatch, tmp_path):
    monkeypatch.setenv("KEY_U", "sk-uuuuuuuuuuuuuuuuuuuuUUUU")
    router = KeyRouter([KeyEntry("main", ["text"], "KEY_U", base_url="http://x", models={"*": "m"},
                                 limits={"requests_per_day": 10},
                                 pricing={"input_per_1m": 1000, "output_per_1m": 2000})], tmp_path / "usage.json")

    class Client:
        def chat(self, messages, tools=None):
            return LLMReply({"role": "assistant", "content": "hi"}, 1000, 100)
    llm = RoutedLLM(router, "text", client_factory=lambda *a: Client())
    reply = llm.chat([{"role": "user", "content": "x"}])
    assert reply.key == "main" and abs(reply.cost - (1.0 + 0.2)) < 1e-9
    base, h = make(lambda: llm, key_router=router)
    tid = call(base, "POST", "/tasks", {"task": "hello"})[1]["id"]
    finished(base, tid)
    u = call(base, "GET", "/usage")[1]
    assert abs(u["total"]["cost"] - 1.2) < 1e-9
    k = u["keys"]["keys"][0]
    assert k["key"] == "sk-u…UUUU" and k["limits"]["requests_per_day"]["used"] == 2
    assert "sk-uuuuuuuuuuuuuuuuuuuu" not in json.dumps(u)


# ---------------------------------------------------------------- 6. export
def test_export_markdown_and_json_with_audit(make, ws, tmp_path):
    secret = "ghp_abcdefghijklmnopqrstuvwx1234"
    llms = iter([MockLLM([{"tool": "write_file", "args": {"path": "e.txt", "content": secret}},
                          {"content": f"wrote it, token {secret}"}]), MockLLM([{"content": "other"}])])
    base, h = make(lambda: next(llms))
    tid = call(base, "POST", "/tasks", {"task": "export me"})[1]["id"]
    call(base, "POST", f"/approvals/{pending(base)[0]['id']}", {"decision": "approve"})
    finished(base, tid)
    other = call(base, "POST", "/tasks", {"task": "other conversation"})[1]["id"]
    finished(base, other)

    with urllib.request.urlopen(f"{base}/tasks/{tid}/export?format=json") as r:
        assert r.headers["Content-Type"].startswith("application/json")
        assert f'conversation-{tid}.json' in r.headers["Content-Disposition"]
        raw = r.read().decode()
    b = json.loads(raw)
    assert b["conversation"]["id"] == tid and b["events"][0]["kind"] == "user"
    assert b["audit"] and {a["task_id"] for a in b["audit"]} == {tid}
    assert [a["tool"] for a in b["audit"]] == ["write_file"]
    assert secret not in raw and "REDACTED" in raw
    with urllib.request.urlopen(f"{base}/tasks/{tid}/export?format=md") as r:
        assert r.headers["Content-Type"].startswith("text/markdown")
        md = r.read().decode()
    assert md.startswith(f"# Conversation {tid}") and "## Audit trail" in md and "## Usage" in md
    assert "### You — turn 1" in md and "`write_file`" in md and "approved" in md and secret not in md
    assert call(base, "GET", f"/tasks/{tid}/export?format=pdf")[0] == 400
    assert call(base, "GET", "/tasks/0000/export")[0] == 404


# ---------------------------------------------------------------- 7. schedules
def test_schedule_validation_and_next_run():
    with pytest.raises(ValueError):
        schedule.validate({"prompt": "x"})
    with pytest.raises(ValueError):
        schedule.validate({"prompt": "x", "every_minutes": 0.5})
    with pytest.raises(ValueError):
        schedule.validate({"prompt": "x", "daily_at": "25:00"})
    with pytest.raises(ValueError):
        schedule.validate({"prompt": "x", "every_minutes": 5, "daily_at": "10:00"})
    with pytest.raises(ValueError):
        schedule.validate({"prompt": " ", "every_minutes": 5})
    t = time.mktime((2026, 11, 12, 10, 0, 0, 0, 0, -1))
    assert schedule.next_daily("10:30", t) == t + 1800
    assert schedule.next_daily("10:00", t) == time.mktime((2026, 11, 13, 10, 0, 0, 0, 0, -1))
    assert schedule.next_run({"kind": "interval", "every_minutes": 5}, t) == t + 300


def test_scheduled_runs_use_same_approvals_and_persist(make, ws, tmp_path):
    clock = Clock()
    base, h = make(lambda: MockLLM(write_script("sched.txt")), clock=clock, db=True)
    st, s = call(base, "POST", "/schedules", {"prompt": "write the report", "every_minutes": 5})
    assert st == 201 and s["kind"] == "interval" and s["next_run"] == clock.t + 300 and s["enabled"]
    assert call(base, "POST", "/schedules", {"prompt": "bad", "daily_at": "7h"})[0] == 400
    assert h.run_due() == []                         # not due yet
    clock.t += 301
    [task] = h.run_due()
    assert task.source == f"schedule:{s['id']}" and task.text == "write the report"
    ap = pending(base)[0]                             # same approval queue as the chat
    assert ap["task"] == task.id and ap["tool"] == "write_file"
    clock.t += 300
    assert h.run_due() == []                          # previous run still waiting: skipped, no overlap
    assert h.list_schedules()[0]["skipped"] == 1
    call(base, "POST", f"/approvals/{ap['id']}", {"decision": "approve"})
    finished(base, task.id)
    assert (ws / "sched.txt").exists()
    # disable / enable / run now / delete
    assert call(base, "POST", f"/schedules/{s['id']}", {"enabled": False})[1]["enabled"] is False
    clock.t += 3600
    assert h.run_due() == []
    assert call(base, "POST", f"/schedules/{s['id']}", {})[0] == 400
    en = call(base, "POST", f"/schedules/{s['id']}", {"enabled": True})[1]
    assert en["next_run"] == clock.t + 300           # no burst of missed runs
    st, r = call(base, "POST", f"/schedules/{s['id']}/run", {})
    assert st == 202 and r["task"]["source"] == f"schedule:{s['id']}"
    call(base, "POST", "/stop-all", {})
    finished(base, r["task"]["id"])
    # persisted: a restarted harness has the schedule (with its counters)
    _, h2 = make(lambda: MockLLM(), clock=clock, db=True, serve=False)
    [s2] = h2.list_schedules()
    assert s2["id"] == s["id"] and s2["runs"] == 2 and s2["skipped"] == 1 and s2["when"] == "every 5 min"
    assert h2.get(task.id).source == f"schedule:{s['id']}"
    assert call(base, "POST", f"/schedules/{s['id']}/delete", {})[0] == 200
    assert call(base, "GET", "/schedules")[1]["schedules"] == []
    assert call(base, "POST", "/schedules/0000/run", {})[0] == 404
    evs = [a["event"] for a in audit_lines(tmp_path) if a.get("event", "").startswith("schedule_")]
    assert evs[:3] == ["schedule_created", "schedule_run", "schedule_skipped"] and "schedule_deleted" in evs


def test_scheduler_thread_fires(make):
    clock = Clock()
    base, h = make(lambda: MockLLM([{"content": "tick"}]), clock=clock, scheduler_tick=0.05)
    sid = h.add_schedule({"prompt": "tick", "every_minutes": 1})["id"]
    clock.t += 61
    t = wait_for(lambda: [x for x in h.list() if x["source"] == f"schedule:{sid}"])[0]
    assert finished(base, t["id"])["result"] == "tick"


# ---------------------------------------------------------------- 8. health
def test_health_masked_keys_and_no_network_by_default(make, monkeypatch, tmp_path):
    monkeypatch.setenv("KEY_H", "sk-hhhhhhhhhhhhhhhhhhhhHHHH")
    hits = []

    class Fake(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append((self.path, self.headers.get("Authorization")))
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass
    fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{fake.server_address[1]}/v1"
    router = KeyRouter([KeyEntry("h", ["text"], "KEY_H", base_url=url, models={"*": "m"})], tmp_path / "u.json")
    base, h = make(lambda: MockLLM(), key_router=router, db=True)
    st, hl = call(base, "GET", "/health")
    assert st == 200 and hl["status"] == "ok" and hl["persistence"].endswith("harness.sqlite3")
    assert hl["keys"]["mode"] == "router" and hl["keys"]["keys"][0]["key"] == "sk-h…HHHH"
    assert hl["backend"] == {"checked": False, "urls": [url]} and hits == []
    assert "sk-hhhhhhhhhhhhhhhhhhhh" not in json.dumps(hl)
    st, hl = call(base, "GET", "/health?check=1")
    r = hl["backend"]["results"][0]
    assert r["reachable"] is True and r["http_status"] == 401
    assert hits == [("/v1/models", None)]            # probe never sends the API key
    fake.shutdown()
    fake.server_close()


def test_health_single_key_mode_and_token(make):
    base, h = make(lambda: MockLLM(), token="t0k", backend={"provider": "groq", "model": "m",
                                                           "base_url": "http://127.0.0.1:9/none", "key": "gsk_…ABCD"})
    assert call(base, "GET", "/health")[0] == 401
    hl = call(base, "GET", "/health", headers={"Authorization": "Bearer t0k"})[1]
    assert hl["keys"] == {"mode": "single-key (.env)", "provider": "groq", "model": "m", "key": "gsk_…ABCD"}
    assert hl["persistence"] is None and hl["tasks"] == {} and hl["pending_approvals"] == 0
    hl = call(base, "GET", "/health?check=1", headers={"Authorization": "Bearer t0k"})[1]
    assert hl["backend"]["results"][0]["reachable"] is False


def test_remember_on_already_answered_approval_leaves_no_rule(make, ws, tmp_path):
    base, h = make(lambda: MockLLM(write_script("late.txt")))
    tid = call(base, "POST", "/tasks", {"task": "w"})[1]["id"]
    ap = pending(base)[0]
    assert call(base, "POST", f"/approvals/{ap['id']}", {"decision": "deny"})[0] == 200
    st, _ = call(base, "POST", f"/approvals/{ap['id']}", {"decision": "approve", "remember": "session"})
    assert st == 409 and h.list_rules() == []
    finished(base, tid)
    evs = [a["event"] for a in audit_lines(tmp_path) if a.get("event", "").startswith("rule_")]
    assert evs == []          # already answered: no rule is created at all
