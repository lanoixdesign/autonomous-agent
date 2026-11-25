"""v0.9.16: agent grid — progress fill and per-agent history from events."""
from agent import __version__, i18n
from agent.harness import Task, history_of, tile_progress
from agent.harness_chat import CHAT_PAGE


def test_tile_progress():
    assert tile_progress(3, 5, "running") == (0.6, False)
    assert tile_progress(0, None, "running") == (0.0, True)
    assert tile_progress(0, 0, "queued") == (0.0, True)
    assert tile_progress(2, 8, "done") == (1.0, False)
    assert tile_progress(1, 4, "error") == (1.0, False)
    assert tile_progress(5, 5, "cancelling") == (1.0, False)


def test_history_of_filters_and_shapes_events():
    evs = [
        {"kind": "user", "text": "Write a summary", "ts": 1},
        {"kind": "audit", "agent": "root.1", "tool": "read_file", "ok": True, "ts": 2},
        {"kind": "audit", "agent": "root.2", "tool": "web_search", "ok": False, "ts": 3},
        {"kind": "progress", "agent": "root.1", "steps": 2, "max_steps": 5, "ts": 4},
        {"kind": "message", "agent": "root.1", "content": "Draft ready", "ts": 5},
        {"kind": "status", "status": "running", "ts": 6},
    ]
    h1 = history_of(evs, "root.1")
    assert [x["action"] for x in h1] == ["read_file", "progress", "message"]
    assert h1[0]["status"] == "ok" and h1[1]["steps"] == 2 and h1[2]["text"] == "Draft ready"
    h2 = history_of(evs, "root.2")
    assert h2 == [{"ts": 3, "kind": "audit", "status": "error", "action": "web_search", "ok": False}]
    root = history_of(evs, "root")
    assert [x["action"] for x in root] == ["user", "status"]
    assert root[0]["text"] == "Write a summary"


def test_graph_includes_progress_flag_and_history():
    t = Task("Plan a trip")
    t.agents["root"]["status"] = "running"
    t.agents["root.1"] = {"id": "root.1", "parent": "root", "depth": 1, "task": "Find trains",
                          "status": "running", "steps": 2, "max_steps": 4, "role": "research"}
    t.add_event("audit", agent="root.1", tool="web_search", ok=True)
    g = t.graph()
    root = next(a for a in g["agents"] if a["id"] == "root")
    kid = next(a for a in g["agents"] if a["id"] == "root.1")
    assert kid["progress"] == 0.5 and kid["indeterminate"] is False
    assert root["indeterminate"] is True and root["progress"] == 0.0
    assert kid["history"] and kid["history"][0]["action"] == "web_search"
    t.agents["root.1"]["status"] = "error"
    assert t.graph()["agents"][1]["progress"] == 1.0 and t.graph()["agents"][1]["indeterminate"] is False


def test_chat_page_has_the_grid_and_strings():
    assert "swgrid" in CHAT_PAGE and "atile" in CHAT_PAGE and "openAgent" in CHAT_PAGE
    assert "class=\"mascot\"" in CHAT_PAGE and "atileblink" in CHAT_PAGE
    assert "prefers-reduced-motion" in CHAT_PAGE and "classList.toggle(\"working\"" in CHAT_PAGE
    assert "agpanel" in CHAT_PAGE
    for k in ("grid.history", "grid.close", "grid.empty", "grid.step", "grid.act.user"):
        assert i18n.EN[k] and i18n.FR[k] and i18n.EN[k] != i18n.FR[k]
