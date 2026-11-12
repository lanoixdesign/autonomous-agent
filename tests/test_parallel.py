import json
import threading
import time

from agent.audit import AuditLog
from agent.llm import LLMReply
from agent.loop import Budget
from agent.permissions import Permissions
from agent.swarm import SwarmConfig, parallel_safe

ALLOW_DELEGATE = {"defaults": {"delegate": "allow"}}
BIG = Budget(max_steps=200, max_tool_calls=200, max_tokens=10 ** 7)


class FanOutLLM:
    """Root (task 'root') calls spawn_agents once, then answers. Each child sleeps then answers,
    while we measure how many children are inside the model call at the same time."""

    def __init__(self, n, allowed_tools, delay=0.15):
        self.n, self.allowed, self.delay = n, allowed_tools, delay
        self.lock = threading.Lock()
        self.active = self.peak = 0

    def chat(self, messages, tools=None):
        task = messages[1]["content"]
        if task == "root":
            if not any(m["role"] == "tool" for m in messages):
                args = {"tasks": [f"t{i}" for i in range(self.n)]}
                if self.allowed is not None:
                    args["allowed_tools"] = self.allowed
                return LLMReply({"role": "assistant", "content": None, "tool_calls": [
                    {"id": "s", "type": "function", "function": {"name": "spawn_agents", "arguments": json.dumps(args)}}]}, 1, 1)
            return LLMReply({"role": "assistant", "content": "root done"}, 1, 1)
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        return LLMReply({"role": "assistant", "content": f"done {task}"}, 1, 1)


def run_fanout(make_agent, n, allowed, max_parallel, max_children=10, perms=None, confirm=None):
    llm = FanOutLLM(n, allowed)
    agent = make_agent(llm, perms=perms or Permissions.from_dict(ALLOW_DELEGATE), budget=BIG, confirm=confirm,
                       swarm=SwarmConfig(max_parallel=max_parallel, max_children=max_children))
    res = agent.run("root")
    return llm, agent, res


def test_parallel_children_overlap_and_respect_cap(make_agent):
    t0 = time.monotonic()
    llm, _, res = run_fanout(make_agent, 6, ["read_file", "list_files"], max_parallel=3)
    elapsed = time.monotonic() - t0
    assert res.answer == "root done"
    assert llm.peak == 3                       # overlapped, and never more than max_parallel
    assert elapsed < 6 * 0.15                  # faster than sequential
    obs = [m["content"] for m in res.messages if m["role"] == "tool"][0]
    assert [f"done t{i}" in obs for i in range(6)] == [True] * 6   # answers kept in task order
    assert obs.index("done t0") < obs.index("done t5")
    llm, _, _ = run_fanout(make_agent, 6, ["read_file"], max_parallel=2)
    assert llm.peak == 2


def test_terminal_mode_keeps_approval_needing_children_sequential(make_agent):
    # write is "ask" and the confirm callback is a terminal-style function -> sequential
    assert run_fanout(make_agent, 3, ["read_file", "write_file"], 3, confirm=lambda *a: False)[0].peak == 1
    # no allowed_tools = all the parent's tools (some are "ask") -> sequential
    assert run_fanout(make_agent, 3, None, 3)[0].peak == 1
    # max_parallel=1 -> sequential
    assert run_fanout(make_agent, 3, ["read_file"], 1)[0].peak == 1


def test_writing_children_run_in_parallel_when_no_prompt_can_mix(make_agent):
    # writers that never need an approval: parallel, each in an isolated copy
    perms = Permissions.from_dict({"defaults": {"delegate": "allow", "write": "allow"}})
    assert run_fanout(make_agent, 3, ["read_file", "write_file"], 3, perms=perms)[0].peak == 3

    # writers that need approval, with a confirm that accepts concurrent approvals (like the harness)
    class Concurrent:
        concurrent = True

        def __call__(self, *a):
            return True
    assert run_fanout(make_agent, 3, ["read_file", "write_file"], 3, confirm=Concurrent())[0].peak == 3


def test_parallel_safe_rules(make_agent):
    from agent.tools import Tool, params
    agent = make_agent(FanOutLLM(1, None), perms=Permissions(), swarm=SwarmConfig())
    agent.registry.add(Tool("net", "network tool", "network", params([]), lambda c, a: ""))
    assert parallel_safe(agent, ["read_file", "list_files"])
    assert not parallel_safe(agent, None)
    assert not parallel_safe(agent, ["read_file", "shell"])           # execute
    assert not parallel_safe(agent, ["read_file", "net"])             # network defaults to ask
    assert not parallel_safe(agent, ["read_file", "spawn_agent"])     # delegate
    assert not parallel_safe(agent, ["nope"])
    agent.permissions = Permissions.from_dict({"defaults": {"network": "allow"}})
    assert parallel_safe(agent, ["read_file", "net"])


def test_thread_safe_child_counter_and_budget(make_agent):
    llm, agent, res = run_fanout(make_agent, 12, ["read_file"], max_parallel=6, max_children=7)
    obs = [m["content"] for m in res.messages if m["role"] == "tool"][0]
    started = [line for line in obs.splitlines() if line.startswith("[sub-agent root.")]
    assert len(started) == 7 and obs.count("max sub-agents per run reached (7)") == 5
    assert sorted(line.split()[1] for line in started) == sorted(f"root.{i}]" for i in range(1, 8))
    assert agent.swarm_state.spawned == 7
    st = agent.state
    assert (st.reserved_steps, st.reserved_calls, st.reserved_tokens) == (0, 0, 0)
    assert res.steps == 2 + 7                  # root's 2 model calls + one per child


def test_parallel_children_cannot_exceed_parent_budget(make_agent):
    llm = FanOutLLM(4, ["read_file"])
    agent = make_agent(llm, perms=Permissions.from_dict(ALLOW_DELEGATE),
                       budget=Budget(max_steps=5, max_tool_calls=50, max_tokens=10 ** 6),
                       swarm=SwarmConfig(max_parallel=4))
    res = agent.run("root")
    # 4 steps left after the root's first call, shared by 4 concurrent children -> 1 step each
    assert res.steps <= 5


def test_audit_writes_are_thread_safe(tmp_path):
    path = tmp_path / "a.jsonl"

    def writer(i):
        log = AuditLog(path)
        for j in range(100):
            log.record(tool="t", worker=i, j=j, pad="x" * 300)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = [json.loads(x) for x in path.read_text().splitlines()]
    assert len(lines) == 800 and len({(l["worker"], l["j"]) for l in lines}) == 800
