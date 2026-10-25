import json

from agent.audit import AuditLog
from agent.llm import LLMError, MockLLM
from agent.loop import Budget
from agent.permissions import Permissions


def audit_lines(tmp_path):
    return [json.loads(x) for x in (tmp_path / "state" / "audit.jsonl").read_text().splitlines()]


def test_default_mock_plan_end_to_end(make_agent, tmp_path):
    agent = make_agent(MockLLM())
    res = agent.run("what is here?")
    assert res.stop_reason == "final"
    assert res.tool_calls == 2 and res.steps == 3
    assert "hello.txt" in res.answer
    lines = audit_lines(tmp_path)
    assert [l["tool"] for l in lines] == ["list_files", "memory_recall"]
    assert all(l["decision"] == "allow" for l in lines)


def test_ask_refused_without_terminal_and_audited(make_agent, ws, tmp_path):
    llm = MockLLM([{"tool": "write_file", "args": {"path": "x.txt", "content": "hi"}}, {"content": "done"}])
    res = make_agent(llm).run("write")
    assert res.stop_reason == "final"
    assert not (ws / "x.txt").exists()
    tool_msg = [m for m in res.messages if m["role"] == "tool"][0]["content"]
    assert tool_msg.startswith("DENIED")
    assert audit_lines(tmp_path)[0]["decision"] == "deny"


def test_ask_approved_by_confirm(make_agent, ws):
    seen = []
    llm = MockLLM([{"tool": "write_file", "args": {"path": "x.txt", "content": "hi"}}, {"content": "done"}])
    make_agent(llm, confirm=lambda *a: seen.append(a) or True).run("write")
    assert (ws / "x.txt").read_text() == "hi"
    assert seen[0][0] == "write_file" and seen[0][1] == "write"


def test_denied_path_never_reaches_tool(make_agent):
    llm = MockLLM([{"tool": "read_file", "args": {"path": ".env"}}, {"content": "ok"}])
    res = make_agent(llm, confirm=lambda *a: True).run("read env")
    obs = [m for m in res.messages if m["role"] == "tool"][0]["content"]
    assert "DENIED" in obs and "SECRET=1" not in obs


def test_spend_denied_even_with_yolo(make_agent, ctx):
    from agent.tools import Tool, params
    calls = []
    agent = make_agent(MockLLM([{"tool": "buy", "args": {}}, {"content": "ok"}]), perms=Permissions(yolo=True),
                       confirm=lambda *a: True)
    agent.registry.add(Tool("buy", "buy something", "spend", params([]), lambda c, a: calls.append(1) or "bought"))
    agent.run("buy")
    assert calls == []


def test_budget_max_steps(make_agent):
    llm = MockLLM([{"tool": "list_files", "args": {"path": "."}}] * 3 + [{"tool": "read_file", "args": {"path": "hello.txt"}}] * 3)
    res = make_agent(llm, budget=Budget(max_steps=2, max_repeats=99)).run("loop")
    assert res.stop_reason == "max_steps" and res.steps == 2


def test_budget_max_tool_calls_and_tokens(make_agent):
    many = [{"tools": [{"tool": "list_files", "args": {"path": "."}}, {"tool": "memory_recall", "args": {"query": str(i)}}]} for i in range(5)]
    res = make_agent(MockLLM(list(many)), budget=Budget(max_tool_calls=3, max_repeats=99)).run("x")
    assert res.stop_reason == "max_tool_calls"
    res = make_agent(MockLLM(list(many)), budget=Budget(max_tokens=10, max_repeats=99)).run("x")
    assert res.stop_reason == "max_tokens" and res.steps == 1


def test_no_progress_stop(make_agent):
    llm = MockLLM([{"tool": "list_files", "args": {"path": "."}}] * 10)
    res = make_agent(llm, budget=Budget(max_repeats=3)).run("x")
    assert res.stop_reason == "no_progress" and res.tool_calls == 3


def test_custom_stop_rule(make_agent):
    llm = MockLLM([{"tool": "list_files", "args": {"path": str(i)}} for i in range(10)])
    res = make_agent(llm, stop_rule=lambda st: "idc_stop" if st.tool_calls >= 2 else None).run("x")
    assert res.stop_reason == "idc_stop"


def test_llm_error_and_unknown_tool_and_bad_json(make_agent):
    class Boom:
        def chat(self, *a):
            raise LLMError("down")
    assert make_agent(Boom()).run("x").stop_reason == "llm_error"
    res = make_agent(MockLLM([{"tool": "nope", "args": {}}, {"content": "ok"}])).run("x")
    assert "unknown tool" in [m for m in res.messages if m["role"] == "tool"][0]["content"]


def test_secrets_never_in_audit(make_agent, tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fakefakefakefakefake1234")
    llm = MockLLM([{"tool": "memory_write", "args": {"text": "key=gsk_fakefakefakefakefake1234 token ghp_abcdefghijklmnopqrstuvwx"}},
                   {"tool": "shell", "args": {"command": "echo gsk_fakefakefakefakefake1234"}},
                   {"content": "done"}])
    make_agent(llm, perms=Permissions.from_dict({"tools": {"memory_write": "allow", "shell": "allow"}})).run("x")
    raw = (tmp_path / "state" / "audit.jsonl").read_text()
    assert "gsk_fake" not in raw and "ghp_abc" not in raw and "REDACTED" in raw


def test_audit_is_append_only(tmp_path):
    a = AuditLog(tmp_path / "a.jsonl")
    a.record(tool="t1")
    first = (tmp_path / "a.jsonl").read_text()
    a.record(tool="t2")
    assert (tmp_path / "a.jsonl").read_text().startswith(first)
    assert [e["tool"] for e in a.tail()] == ["t1", "t2"]


def test_chat_keeps_history(make_agent):
    agent = make_agent(MockLLM([{"content": "one"}, {"content": "two"}]))
    agent.run("first")
    agent.run("second")
    assert [m["content"] for m in agent.messages if m["role"] == "user"] == ["first", "second"]
