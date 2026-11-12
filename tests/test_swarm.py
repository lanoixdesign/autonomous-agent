import json

from agent.llm import MockLLM
from agent.loop import Budget
from agent.permissions import Permissions
from agent.swarm import SwarmConfig

ALLOW_DELEGATE = {"defaults": {"delegate": "allow"}}


def audit_lines(tmp_path):
    return [json.loads(x) for x in (tmp_path / "state" / "audit.jsonl").read_text().splitlines()]


def tool_obs(res):
    return [m["content"] for m in res.messages if m["role"] == "tool"]


def test_spawn_returns_child_result(make_agent):
    # One shared mock script: parent spawns -> child reads a file and answers -> parent answers.
    llm = MockLLM([{"tool": "spawn_agent", "args": {"task": "read hello.txt"}},
                   {"tool": "read_file", "args": {"path": "hello.txt"}},
                   {"content": "child says: hello world"},
                   {"content": "parent done"}])
    agent = make_agent(llm, perms=Permissions.from_dict(ALLOW_DELEGATE), swarm=SwarmConfig())
    res = agent.run("delegate")
    assert res.stop_reason == "final" and res.answer == "parent done"
    obs = tool_obs(res)[0]
    assert obs.startswith("[sub-agent root.1] stop=final") and "child says: hello world" in obs
    # the child's usage is deducted from the parent's budget
    assert res.steps == 4 and res.tool_calls == 2


def test_swarm_off_by_default(make_agent):
    agent = make_agent(MockLLM([{"content": "x"}]))
    assert "spawn_agent" not in agent.registry
    assert "spawn_agent" in make_agent(MockLLM(), swarm=SwarmConfig()).registry
    assert "spawn_agent" not in make_agent(MockLLM(), swarm=SwarmConfig(max_depth=0)).registry


def test_spawn_needs_permission(make_agent):
    llm = MockLLM([{"tool": "spawn_agent", "args": {"task": "x"}}, {"content": "ok"}])
    res = make_agent(llm, swarm=SwarmConfig()).run("x")   # delegate: ask, no terminal -> refused
    assert tool_obs(res)[0].startswith("DENIED") and llm.calls == 2


def test_depth_limit_enforced(make_agent, tmp_path):
    llm = MockLLM([{"tool": "spawn_agent", "args": {"task": "level 1"}},
                   {"tool": "spawn_agent", "args": {"task": "level 2"}},
                   {"tool": "spawn_agent", "args": {"task": "level 3"}},
                   {"content": "leaf"},
                   {"content": "level 1 done"},
                   {"content": "root done"}])
    agent = make_agent(llm, perms=Permissions.from_dict(ALLOW_DELEGATE), swarm=SwarmConfig(max_depth=2))
    res = agent.run("go")
    assert res.answer == "root done"
    lines = audit_lines(tmp_path)
    spawns = [l for l in lines if l.get("event") == "spawn"]
    assert [(s["child"], s["child_depth"]) for s in spawns] == [("root.1", 1), ("root.1.2", 2)]
    # the depth-2 agent has no spawn tool at all: its call is refused as an unknown tool
    refused = [l for l in lines if l.get("decision") == "unknown_tool"]
    assert len(refused) == 1 and refused[0]["agent"] == "root.1.2" and refused[0]["depth"] == 2


def test_child_count_limit_enforced(make_agent, tmp_path):
    llm = MockLLM([{"tool": "spawn_agents", "args": {"tasks": ["a", "b", "c"]}},
                   {"content": "A"}, {"content": "B"},
                   {"content": "root done"}])
    agent = make_agent(llm, perms=Permissions.from_dict(ALLOW_DELEGATE), swarm=SwarmConfig(max_children=2))
    res = agent.run("fan out")
    obs = tool_obs(res)[0]
    assert "[sub-agent root.1]" in obs and "[sub-agent root.2]" in obs
    assert "max sub-agents per run reached (2)" in obs
    assert res.answer == "root done"
    # the counter is per root run
    llm.script = [{"tool": "spawn_agent", "args": {"task": "again"}}, {"content": "C"}, {"content": "ok"}]
    assert "[sub-agent root.1] stop=final" in tool_obs(agent.run("second run"))[-1]


def test_child_cannot_use_tool_parent_denies(make_agent, ws):
    perms = Permissions.from_dict({"defaults": {"delegate": "allow"}, "tools": {"write_file": "deny"}})
    llm = MockLLM([{"tool": "spawn_agent", "args": {"task": "write"}},
                   {"tool": "write_file", "args": {"path": "x.txt", "content": "hi"}},
                   {"content": "could not write"},
                   {"content": "ok"}])
    # even a confirm callback that says yes to everything cannot widen the parent's deny
    res = make_agent(llm, perms=perms, confirm=lambda *a: True, swarm=SwarmConfig()).run("x")
    assert not (ws / "x.txt").exists()
    child_msgs = [m["content"] for m in res.messages if m["role"] == "tool"]
    assert "could not write" in child_msgs[0]


def test_child_allowed_tools_narrow_and_never_widen(make_agent, ws, tmp_path):
    perms = Permissions.from_dict({"defaults": {"delegate": "allow", "write": "allow"}})
    llm = MockLLM([{"tool": "spawn_agent", "args": {"task": "t", "allowed_tools": ["read_file", "made_up_tool"]}},
                   {"tool": "write_file", "args": {"path": "x.txt", "content": "hi"}},
                   {"content": "child done"},
                   {"content": "ok"}])
    make_agent(llm, perms=perms, swarm=SwarmConfig()).run("x")
    assert not (ws / "x.txt").exists()
    spawn = [l for l in audit_lines(tmp_path) if l.get("event") == "spawn"][0]
    assert spawn["tools"] == ["read_file"]


def test_send_and_spend_stay_denied_for_children(make_agent):
    from agent.tools import Tool, params
    calls = []
    perms = Permissions.from_dict(ALLOW_DELEGATE, yolo=True)
    agent = make_agent(MockLLM([{"tool": "spawn_agent", "args": {"task": "buy"}},
                                {"tool": "buy", "args": {}}, {"content": "no"}, {"content": "ok"}]),
                       perms=perms, swarm=SwarmConfig())
    agent.base_registry.add(Tool("buy", "buy", "spend", params([]), lambda c, a: calls.append(1) or "bought"))
    agent.run("x")
    assert calls == []


def test_child_budget_capped_by_parent(make_agent, tmp_path):
    llm = MockLLM([{"tool": "spawn_agent", "args": {"task": "loop", "max_steps": 50}}]
                  + [{"tool": "list_files", "args": {"path": str(i)}} for i in range(10)])
    res = make_agent(llm, perms=Permissions.from_dict(ALLOW_DELEGATE), swarm=SwarmConfig(),
                     budget=Budget(max_steps=4, max_repeats=99)).run("x")
    spawn = [l for l in audit_lines(tmp_path) if l.get("event") == "spawn"][0]
    assert spawn["budget"]["max_steps"] == 3
    assert res.stop_reason == "max_steps"


def test_audit_records_spawn_with_agent_ids(make_agent, tmp_path):
    llm = MockLLM([{"tool": "spawn_agent", "args": {"task": "list"}},
                   {"tool": "list_files", "args": {"path": "."}},
                   {"content": "files listed"},
                   {"content": "done"}])
    make_agent(llm, perms=Permissions.from_dict(ALLOW_DELEGATE), swarm=SwarmConfig()).run("x")
    lines = audit_lines(tmp_path)
    assert [(l.get("event") or l["tool"], l["agent"], l["depth"]) for l in lines] == [
        ("spawn", "root", 0),
        ("list_files", "root.1", 1),
        ("child_done", "root.1", 1),
        ("spawn_agent", "root", 0),
    ]
    assert lines[0]["child"] == "root.1" and lines[0]["task"] == "list"
    assert lines[2]["stop_reason"] == "final" and lines[2]["result"] == "files listed"
    assert lines[3]["category"] == "delegate" and lines[3]["decision"] == "allow"
