"""IDC mode (agent/idc.py): off = unchanged, decay, forced collapse, append-only commitments,
'I don't know' cheaper than unsupported claims, vitality inherited by sub-agents, harness toggles, i18n."""
import json
import subprocess
import sys
import threading

import pytest

from agent import i18n
from agent.harness import Harness, make_server
from agent.idc import IDC, IDCConfig, TOOL_NAME
from agent.llm import LLMReply, MockLLM
from agent.loop import Agent, Budget
from agent.permissions import Permissions
from agent.store import Store
from agent.swarm import SwarmConfig
from agent.tools import default_registry

from test_harness import call, finished

REPO = __import__("pathlib").Path(__file__).resolve().parent.parent


class Recorder(MockLLM):
    """MockLLM that remembers the tool list it was offered at each call."""

    def __init__(self, script):
        super().__init__(script)
        self.offered = []

    def chat(self, messages, tools=None):
        self.offered.append([t["function"]["name"] for t in tools or []])
        return super().chat(messages, tools)


def cfg(**kw):
    return IDCConfig(enabled=True, **kw).validate()


def commit(kind, text, evidence=None, revises=None):
    args = {"kind": kind, "text": text}
    if evidence is not None:
        args["evidence"] = evidence
    if revises:
        args["revises"] = revises
    return {"tool": TOOL_NAME, "args": args}


# ------------------------------------------------------------------ configuration
def test_config_defaults_env_file_and_cli():
    assert IDCConfig.from_sources({}, env={}).enabled is False            # off by default
    assert IDCConfig.from_sources({}, env={"AGENT_IDC": "1"}).enabled is True
    c = IDCConfig.from_sources({"enabled": True, "vitality": 50, "collapse_threshold": 5},
                               env={"AGENT_IDC_STEP_COST": "2.5"}, enabled=False)
    assert (c.enabled, c.vitality, c.collapse_threshold, c.step_cost) == (False, 50.0, 5.0, 2.5)
    with pytest.raises(ValueError, match="unknown setting"):
        IDCConfig.from_sources({"vitalty": 3}, env={})
    with pytest.raises(ValueError, match="cheaper"):
        IDCConfig.from_sources({"unknown_cost": 20, "unsupported_cost": 10}, env={})
    with pytest.raises(ValueError, match="collapse_threshold"):
        IDCConfig.from_sources({"vitality": 10, "collapse_threshold": 10}, env={})


def test_idc_section_in_permissions_file_parses(tmp_path):
    p = tmp_path / "permissions.yaml"
    p.write_text("defaults:\n  read: allow\nidc:\n  enabled: true\n  vitality: 80\n  allow_revise: false\n")
    perms = Permissions.load(p)
    c = IDCConfig.from_sources(perms.idc, env={})
    assert (c.enabled, c.vitality, c.allow_revise) == (True, 80.0, False)


# ------------------------------------------------------------------ off = unchanged
def test_off_means_unchanged(make_agent):
    llm = Recorder([{"tool": "list_files", "args": {"path": "."}}, {"content": "done"}])
    agent = make_agent(llm)
    res = agent.run("list")
    assert (res.answer, res.stop_reason, res.steps, res.tool_calls) == ("done", "final", 2, 1)
    assert all(TOOL_NAME not in names for names in llm.offered)
    assert "IDC" not in agent.messages[0]["content"]
    assert agent.idc is None


# ------------------------------------------------------------------ decay
def test_vitality_decays_with_steps_tools_and_tokens(make_agent):
    llm = Recorder([{"tool": "list_files", "args": {"path": "."}}, {"content": "done"}])
    ctrl = IDC(cfg(step_cost=4, tool_cost=3, token_cost=0.5))
    agent = make_agent(llm, idc=ctrl)
    res = agent.run("list")
    assert res.stop_reason == "final"
    expected = 2 * 4 + 3 + 0.5 * res.tokens / 1000
    assert ctrl.snapshot()["spent"] == pytest.approx(expected, abs=0.01)
    assert ctrl.vitality == pytest.approx(100 - expected, abs=0.01)
    assert all(TOOL_NAME in names for names in llm.offered)          # commit tool offered
    assert "IDC mode is ON" in agent.messages[0]["content"]
    assert ctrl.commitments[-1]["kind"] == "final" and ctrl.commitments[-1]["text"] == "done"
    # a new user turn starts with full vitality, commitments stay
    agent.llm.script = [{"content": "again"}]
    agent.run("again")
    assert ctrl.vitality == pytest.approx(100 - 4 - 0.5 * agent.state.tokens / 1000, abs=0.01)
    assert [c["text"] for c in ctrl.commitments if c["kind"] == "final"] == ["done", "again"]


# ------------------------------------------------------------------ forced collapse
def test_low_vitality_forces_a_tool_free_final_answer(make_agent):
    llm = Recorder([{"tool": "list_files", "args": {"path": "."}},
                    {"content": "good enough: hello.txt exists"}])
    ctrl = IDC(cfg(vitality=30, collapse_threshold=20, step_cost=6, tool_cost=6, token_cost=0))
    events = []
    agent = make_agent(llm, idc=ctrl, on_event=lambda k, d: events.append((k, d)))
    res = agent.run("what is here?")
    # 30 - 6 (step) - 6 (tool) = 18 <= 20 -> collapse: one more call, without tools
    assert res.stop_reason == "idc_collapse"
    assert llm.offered[-1] == []
    assert res.tool_calls == 1
    assert any(k == "idc" and d.get("collapse") == "low_vitality" for k, d in events)
    assert "[IDC controller]" in agent.messages[-2]["content"]


def test_no_new_information_forces_collapse(make_agent):
    same = [{"tool": "list_files", "args": {"path": p}} for p in (".", "./", "")]
    llm = Recorder(same + [{"content": "stopping: nothing new"}])
    ctrl = IDC(cfg(stall_limit=2, token_cost=0))
    res = make_agent(llm, idc=ctrl).run("look")
    assert res.stop_reason == "idc_collapse" and res.answer == "stopping: nothing new"
    assert res.tool_calls == 3 and ctrl.snapshot()["collapsed"] == "no_new_information"


def test_exhaustion_returns_last_supported_answer_or_i_dont_know(make_agent):
    # vitality gone: no more model call, the fallback is built from commitments
    script = [{"tools": [{"tool": "read_file", "args": {"path": "hello.txt"}}]},
              {"tools": [commit("answer", "The file says hello world", ["hello world"]),
                         commit("answer", "The file was written in 1999")]},   # unsupported: never used
              {"content": "never asked"}]
    llm = Recorder(script)
    ctrl = IDC(cfg(vitality=30, collapse_threshold=0, step_cost=6, tool_cost=6, token_cost=0,
                   unsupported_cost=15))
    res = make_agent(llm, idc=ctrl).run("what does hello.txt say?")
    assert res.stop_reason == "idc_exhausted"
    assert res.answer.startswith("The file says hello world")
    assert "1999" not in res.answer.split("\n")[0]
    assert len(llm.offered) == 2

    llm2 = Recorder([{"tool": "list_files", "args": {"path": "."}}, {"content": "never"}])
    ctrl2 = IDC(cfg(vitality=10, collapse_threshold=0, step_cost=6, tool_cost=6), lang="fr")
    res2 = make_agent(llm2, idc=ctrl2).run("question")
    assert res2.stop_reason == "idc_exhausted" and res2.answer.startswith("Je ne sais pas")


# ------------------------------------------------------------------ commitments: append-only, costs
def test_commitments_are_append_only():
    ctrl = IDC(cfg(revise_cost=25, commit_cost=1, token_cost=0))
    ctrl.start_turn("the sky is blue today")
    a = ctrl.commit({"kind": "fact", "text": "sky is blue", "evidence": ["sky is blue"]})
    view = ctrl.commitments
    view[0]["text"] = "tampered"
    view.clear()
    assert ctrl.commitments[0]["text"] == "sky is blue"                  # copies only
    before = ctrl.vitality
    b = ctrl.commit({"kind": "fact", "text": "sky is grey", "evidence": ["sky is blue"], "revises": a["id"]})
    assert before - ctrl.vitality == pytest.approx(26)                    # commit + revise penalty
    assert [c["id"] for c in ctrl.commitments] == [a["id"], b["id"]]     # old entry kept
    assert ctrl.commitments[1]["revises"] == a["id"]
    with pytest.raises(Exception, match="unknown commitment"):
        ctrl.commit({"kind": "fact", "text": "x", "revises": "nope"})
    strict = IDC(cfg(allow_revise=False))
    c1 = strict.commit({"kind": "unknown", "text": "no idea"})
    with pytest.raises(Exception, match="irreversible"):
        strict.commit({"kind": "fact", "text": "y", "revises": c1["id"]})
    assert len(strict.commitments) == 1
    assert not hasattr(ctrl, "delete") and not hasattr(ctrl, "edit")


def test_i_dont_know_is_cheaper_than_an_unsupported_claim(make_agent):
    llm = Recorder([{"tool": "read_file", "args": {"path": "hello.txt"}},
                    {"tools": [commit("fact", "hello.txt starts with hello world", ["hello world"]),
                               commit("fact", "the author is Ada", ["written by Ada"]),
                               commit("unknown", "I do not know who wrote it")]},
                    {"content": "done"}])
    ctrl = IDC(cfg(commit_cost=1, unknown_cost=0.5, unsupported_cost=15))
    agent = make_agent(llm, idc=ctrl)
    agent.run("who wrote hello.txt?")
    cs = [c for c in ctrl.commitments if c["kind"] != "final"]
    assert [(c["supported"], c["cost"]) for c in cs] == [(True, 1.0), (False, 15.0), (True, 0.5)]
    # the model is told which claim was unsupported
    obs = [m["content"] for m in agent.messages if m["role"] == "tool" and m["content"].startswith("committed")]
    assert ["UNSUPPORTED" in o for o in obs] == [False, True, False]


def test_invalid_commit_is_refused_and_audited(make_agent, tmp_path):
    llm = Recorder([commit("guess", "x"), {"content": "ok"}])
    ctrl = IDC(cfg())
    agent = make_agent(llm, idc=ctrl)
    agent.run("q")
    assert any(m["role"] == "tool" and m["content"].startswith("ERROR: kind must be") for m in agent.messages)
    audit = [json.loads(x) for x in (tmp_path / "state" / "audit.jsonl").read_text().splitlines()]
    assert any(e.get("tool") == TOOL_NAME and e.get("decision") == "invalid" for e in audit)


# ------------------------------------------------------------------ sub-agents inherit a slice
def test_spawned_child_inherits_a_slice_of_vitality(make_agent):
    llm = Recorder([{"tool": "spawn_agent", "args": {"task": "read hello.txt"}},
                    {"tool": "read_file", "args": {"path": "hello.txt"}},     # child
                    {"content": "child: hello world"},                       # child final
                    {"content": "parent done"}])
    perms = Permissions.from_dict({"defaults": {"delegate": "allow"}})
    ctrl = IDC(cfg(step_cost=4, tool_cost=3, token_cost=0, child_share=0.5))
    events = []
    agent = make_agent(llm, perms=perms, idc=ctrl, swarm=SwarmConfig(),
                       on_event=lambda k, d: events.append((k, dict(d))))
    res = agent.run("delegate it")
    assert res.stop_reason == "final"
    child_ev = [d for k, d in events if k == "idc" and d.get("agent") == "root.1"]
    assert child_ev, "the child must report its own vitality"
    # parent: 100 - 4 (first step) = 96 left when spawning -> child gets 96 * 0.5 = 48
    assert child_ev[0]["max"] == pytest.approx(48)
    assert any(d.get("reserved") == pytest.approx(48) for k, d in events if k == "idc" and d.get("agent") == "root")
    # child spent 2 steps + 1 tool = 11; parent pays it, plus its own 2 steps + spawn tool call
    assert ctrl.snapshot()["reserved"] == 0
    assert ctrl.snapshot()["spent"] == pytest.approx(4 + 11 + 3 + 4)
    assert TOOL_NAME in llm.offered[1]                                      # the child can commit too


# ------------------------------------------------------------------ harness
@pytest.fixture
def harness(ctx, tmp_path):
    made = []

    def _make(llm_factory, store=False, default=False):
        def factory(task, audit, confirm, cancel, on_event):
            return Agent(llm_factory(), default_registry(enable_web=False, enable_github=False), Permissions(),
                         audit, ctx, Budget(), confirm=confirm, on_event=on_event, cancel=cancel)
        kw = {"store": Store(tmp_path / "state" / "harness.sqlite3")} if store else {}
        h = Harness(factory, tmp_path / "state" / "audit.jsonl", workspace=ctx.workspace, scheduler_tick=None,
                    idc_config=IDCConfig(enabled=default), **kw)
        srv = make_server(h, "127.0.0.1", 0, None, warn=lambda m: None)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        made.append((srv, h))
        return f"http://127.0.0.1:{srv.server_address[1]}", h

    yield _make
    for srv, h in made:
        h.shutdown(wait=5)
        srv.shutdown()
        if h.store is not None:
            h.store.close()


def test_harness_per_conversation_toggle(harness):
    base, h = harness(lambda: MockLLM())
    st, off = call(base, "POST", "/tasks", {"task": "plain"})
    st, on = call(base, "POST", "/tasks", {"task": "with idc", "idc": True})
    assert (off["idc"], on["idc"]) == (False, True)
    finished(base, off["id"]), finished(base, on["id"])
    ev_off = call(base, "GET", f"/tasks/{off['id']}/events")[1]["events"]
    ev_on = call(base, "GET", f"/tasks/{on['id']}/events")[1]["events"]
    assert not any(e["kind"] == "idc" for e in ev_off)
    assert any(e["kind"] == "idc" and e.get("vitality") is not None for e in ev_on)
    snap = call(base, "GET", f"/tasks/{on['id']}")[1]
    assert snap["idc_state"]["max"] == 100 and snap["idc_state"]["list"][-1]["kind"] == "final"
    # toggle the plain one on, between messages
    st, t = call(base, "POST", f"/tasks/{off['id']}/idc", {"enabled": True})
    assert st == 200 and t["idc"] is True
    call(base, "POST", f"/tasks/{off['id']}/messages", {"text": "again"})
    wait = finished(base, off["id"])
    assert wait["idc"] is True
    ev = call(base, "GET", f"/tasks/{off['id']}/events")[1]["events"]
    assert any(e["kind"] == "idc_toggle" for e in ev) and any(e["kind"] == "idc" for e in ev)
    assert h.get(off["id"]).agent.idc is not None
    assert call(base, "POST", f"/tasks/{off['id']}/idc", {"enabled": "yes"})[0] == 400
    assert call(base, "POST", "/tasks", {"task": "x", "idc": "on"})[0] == 400


def test_harness_records_commitments_and_collapse(harness):
    script = [{"tool": "read_file", "args": {"path": "hello.txt"}},
              {"tools": [commit("fact", "it says hello world", ["hello world"]), commit("fact", "made up")]},
              {"content": "hello world"}]
    base, h = harness(lambda: MockLLM(list(script)))
    st, t = call(base, "POST", "/tasks", {"task": "read it", "idc": True})
    done = finished(base, t["id"])
    assert done["status"] == "done", done
    ev = call(base, "GET", f"/tasks/{t['id']}/events")[1]["events"]
    commits = [e["commit"] for e in ev if e["kind"] == "idc" and e.get("commit")]
    assert [(c["kind"], c["supported"]) for c in commits] == [("fact", True), ("fact", False), ("final", None)]
    audits = [e for e in ev if e["kind"] == "audit" and e.get("event") == "idc_commit"]
    assert [a["commitment"]["id"] for a in audits] == ["root:c1", "root:c2"]


def test_harness_global_default_persists(harness, tmp_path):
    base, h = harness(lambda: MockLLM(), store=True)
    assert call(base, "GET", "/settings")[1]["idc"] is False
    st, s = call(base, "POST", "/settings", {"idc": True})
    assert st == 200 and s["idc"] is True and s["idc_config"]["vitality"] == 100
    st, t = call(base, "POST", "/tasks", {"task": "inherits the default"})
    assert t["idc"] is True
    finished(base, t["id"])
    commitments = call(base, "GET", f"/tasks/{t['id']}")[1]["idc_state"]["list"]
    h.shutdown(wait=5)
    h.store.close()
    base2, h2 = harness(lambda: MockLLM(), store=True)
    assert call(base2, "GET", "/settings")[1]["idc"] is True
    assert call(base2, "GET", f"/tasks/{t['id']}")[1]["idc_state"]["list"] == commitments
    assert call(base2, "GET", "/health")[1]["idc"] == {"default": True}


# ------------------------------------------------------------------ CLI and i18n
def test_cli_run_with_idc_flag(tmp_path):
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("AGENT_")}
    env["PYTHONPATH"] = str(REPO)
    r = subprocess.run([sys.executable, "-m", "agent", "run", "list the files", "--idc", "--provider", "mock",
                        "--offline", "-w", str(tmp_path)], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "[idc] vitality" in r.stderr
    r2 = subprocess.run([sys.executable, "-m", "agent", "run", "list the files", "--provider", "mock",
                         "--offline", "-w", str(tmp_path)], capture_output=True, text=True, env=env, timeout=60)
    assert "[idc]" not in r2.stderr


def test_idc_strings_are_bilingual():
    keys = [k for k in i18n.EN if k.startswith("idc.")]
    assert len(keys) > 20 and all(k in i18n.FR for k in keys)
    ui = i18n.ui_strings()
    assert "idc.vitality" in ui["en"] and "idc.vitality" in ui["fr"]
    assert "status.idc_collapse" in ui["fr"]
