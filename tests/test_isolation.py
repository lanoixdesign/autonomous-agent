import json
import threading
import time

from agent import isolation
from agent.llm import LLMReply
from agent.loop import Budget
from agent.permissions import Permissions
from agent.swarm import SwarmConfig, plan_batch

WRITE_OK = Permissions.from_dict({"defaults": {"delegate": "allow", "write": "allow"}})
BIG = Budget(max_steps=100, max_tool_calls=100, max_tokens=10 ** 7)


def test_isolated_copy_ignores_vcs_venv_and_big_files(ws):
    (ws / ".git").mkdir()
    (ws / ".git" / "HEAD").write_text("ref")
    (ws / ".venv" / "lib").mkdir(parents=True)
    (ws / ".venv" / "lib" / "x.py").write_text("x")
    (ws / "node_modules").mkdir()
    (ws / "sub").mkdir()
    (ws / "sub" / "a.txt").write_text("a")
    (ws / "big.bin").write_bytes(b"0" * 2048)
    (ws / "link").symlink_to(ws / "hello.txt")
    limits = isolation.Limits(max_file_bytes=1024)
    base = isolation.scan(ws, limits)
    assert sorted(base) == [".env", "hello.txt", "sub/a.txt"]
    copy = isolation.make_copy(ws, base, limits)
    try:
        assert copy != ws and (copy / "sub" / "a.txt").read_text() == "a"
        assert not (copy / ".git").exists() and not (copy / "big.bin").exists() and not (copy / "link").exists()
        assert oct(copy.stat().st_mode & 0o777) == "0o700"
        (copy / "hello.txt").write_text("changed in the copy")
        assert (ws / "hello.txt").read_text() == "hello world\nsecond line\n"   # parent untouched
    finally:
        import shutil
        shutil.rmtree(copy)


def test_copy_size_limit(ws):
    base = isolation.scan(ws)
    try:
        isolation.make_copy(ws, base, isolation.Limits(max_total_bytes=5))
    except isolation.WorkspaceTooLarge as e:
        assert "copy limit" in str(e)
    else:
        raise AssertionError("expected WorkspaceTooLarge")


def _children(ws, n):
    base = isolation.scan(ws)
    return base, [(f"root.{i + 1}", isolation.make_copy(ws, base)) for i in range(n)]


def test_merge_without_conflict(ws):
    base, kids = _children(ws, 2)
    (kids[0][1] / "a.txt").write_text("from 1")
    (kids[0][1] / "hello.txt").write_text("edited by 1")
    (kids[1][1] / "b" ).mkdir()
    (kids[1][1] / "b" / "c.txt").write_text("from 2")
    (kids[1][1] / ".env").unlink()
    rep = isolation.merge(ws, base, kids)
    assert rep.conflicts == []
    assert {(a["path"], a["agent"], a["action"]) for a in rep.applied} == {
        ("a.txt", "root.1", "created"), ("hello.txt", "root.1", "modified"),
        ("b/c.txt", "root.2", "created"), (".env", "root.2", "deleted")}
    assert (ws / "a.txt").read_text() == "from 1" and (ws / "b" / "c.txt").read_text() == "from 2"
    assert (ws / "hello.txt").read_text() == "edited by 1" and not (ws / ".env").exists()


def test_merge_conflicts_are_not_overwritten(ws):
    base, kids = _children(ws, 3)
    (kids[0][1] / "hello.txt").write_text("version 1")
    (kids[1][1] / "hello.txt").write_text("version 2")
    (kids[2][1] / "same.txt").write_text("same")       # identical result from two children: fine
    (kids[0][1] / "same.txt").write_text("same")
    (kids[2][1] / ".env").write_text("SECRET=2\n")     # parent changes .env meanwhile -> conflict
    (ws / ".env").write_text("SECRET=parent\n")
    rep = isolation.merge(ws, base, kids)
    assert (ws / "hello.txt").read_text() == "hello world\nsecond line\n"          # untouched
    assert (ws / "hello.txt.conflict-root.1").read_text() == "version 1"
    assert (ws / "hello.txt.conflict-root.2").read_text() == "version 2"
    assert (ws / ".env").read_text() == "SECRET=parent\n"
    assert (ws / ".env.conflict-root.3").read_text() == "SECRET=2\n"
    by = {c["path"]: c for c in rep.conflicts}
    assert by["hello.txt"]["agents"] == ["root.1", "root.2"] and "several" in by["hello.txt"]["reason"]
    assert "parent" in by[".env"]["reason"]
    assert [a["path"] for a in rep.applied] == ["same.txt"] and (ws / "same.txt").read_text() == "same"
    assert "CONFLICT hello.txt" in rep.text()


def test_merge_never_writes_through_a_symlink(ws, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    base, kids = _children(ws, 1)
    (ws / "evil.txt").symlink_to(outside)
    (kids[0][1] / "evil.txt").write_text("pwned")
    rep = isolation.merge(ws, base, kids)
    assert outside.read_text() == "keep" and rep.conflicts and rep.applied == []


class WriterLLM:
    """Root spawns N writer children; child i writes file f{i}.txt and shared.txt (-> conflict)."""

    def __init__(self, n, conflict=True, delay=0.1):
        self.n, self.conflict, self.delay = n, conflict, delay
        self.lock = threading.Lock()
        self.active = self.peak = 0

    def chat(self, messages, tools=None):
        task = messages[1]["content"]
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        if task == "root":
            if not tool_msgs:
                return self._call("spawn_agents", {"tasks": [f"w{i}" for i in range(self.n)],
                                                   "allowed_tools": ["read_file", "write_file"]})
            return LLMReply({"role": "assistant", "content": "root done"}, 1, 1)
        if not tool_msgs:
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            time.sleep(self.delay)
            with self.lock:
                self.active -= 1
            calls = [("write_file", {"path": f"{task}.txt", "content": task})]
            if self.conflict:
                calls.append(("write_file", {"path": "hello.txt", "content": f"by {task}"}))
            return LLMReply({"role": "assistant", "content": None, "tool_calls": [
                {"id": f"{task}{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
                for i, (n, a) in enumerate(calls)]}, 1, 1)
        return LLMReply({"role": "assistant", "content": f"{task} wrote"}, 1, 1)

    @staticmethod
    def _call(name, args):
        return LLMReply({"role": "assistant", "content": None, "tool_calls": [
            {"id": "s", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}, 1, 1)


def test_parallel_writers_isolated_and_merged_with_conflicts(make_agent, ws, tmp_path):
    import tempfile
    from pathlib import Path
    before = set(Path(tempfile.gettempdir()).glob("agent-child-*"))
    llm = WriterLLM(3)
    agent = make_agent(llm, perms=WRITE_OK, budget=BIG, swarm=SwarmConfig(max_parallel=3))
    assert plan_batch(agent, 3, ["read_file", "write_file"]) == "isolated"
    res = agent.run("root")
    assert llm.peak == 3
    assert [(ws / f"w{i}.txt").read_text() for i in range(3)] == ["w0", "w1", "w2"]
    assert (ws / "hello.txt").read_text() == "hello world\nsecond line\n"
    assert sorted(p.name for p in ws.glob("hello.txt.conflict-*")) == [
        "hello.txt.conflict-root.1", "hello.txt.conflict-root.2", "hello.txt.conflict-root.3"]
    obs = [m["content"] for m in res.messages if m["role"] == "tool"][0]
    assert "[merge] CONFLICT hello.txt" in obs and "w0.txt (created by" in obs
    audit = [json.loads(x) for x in (tmp_path / "state" / "audit.jsonl").read_text().splitlines()]
    merge = [l for l in audit if l.get("event") == "merge"][0]
    assert merge["agent"] == "root" and [c["path"] for c in merge["conflicts"]] == ["hello.txt"]
    assert all(l["isolated"] for l in audit if l.get("event") == "spawn")
    assert set(Path(tempfile.gettempdir()).glob("agent-child-*")) == before   # copies removed


def test_isolation_falls_back_to_sequential_when_too_big(make_agent, ws):
    llm = WriterLLM(2, conflict=False)
    cfg = SwarmConfig(max_parallel=2, copy_limits=isolation.Limits(max_total_bytes=1))
    res = make_agent(llm, perms=WRITE_OK, budget=BIG, swarm=cfg).run("root")
    assert llm.peak == 1 and (ws / "w0.txt").exists() and (ws / "w1.txt").exists()
    assert "isolated copies not possible" in [m["content"] for m in res.messages if m["role"] == "tool"][0]
