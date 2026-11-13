"""Live swarm graph: progress events, GET /tasks/{id}/graph, the read-only file link, approval wording (JS)."""
import json
import shutil
import subprocess
import urllib.error
import urllib.request

import pytest

from agent import i18n
from agent.harness_chat import CHAT_PAGE
from agent.llm import MockLLM
from agent.loop import Budget
from agent.swarm import SwarmConfig
from agent.theme import APPROVAL_JS
from test_harness import call, finished, pending, server  # noqa: F401  (fixture)

SCRIPT = [
    {"say": "split", "tool": "spawn_agent", "args": {"task": "Writer: write report.md"}},
    {"tool": "read_file", "args": {"path": "hello.txt"}},                       # root.1, step 1
    {"tool": "write_file", "args": {"path": "report.md", "content": "# report\n"}},   # root.1, step 2
    {"content": "report.md written"},                                           # root.1, step 3
    {"content": "Done: see report.md"},                                         # root
]


def raw(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=10) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def run_swarm(server, ws):
    base, h = server(lambda: MockLLM(list(SCRIPT)), budget=Budget(max_steps=30, max_tool_calls=30, max_tokens=10 ** 7),
                     swarm=SwarmConfig(child_max_steps=5))
    tid = call(base, "POST", "/tasks", {"task": "make a report with a helper"})[1]["id"]
    for _ in range(2):                       # spawn_agent (delegate: ask), then write_file (write: ask)
        ap = pending(base)[0]
        call(base, "POST", f"/approvals/{ap['id']}", {"decision": "approve"})
    done = finished(base, tid)
    assert done["status"] == "done"
    return base, tid


def test_graph_endpoint_and_progress_events(server, ws):
    base, tid = run_swarm(server, ws)
    st, g = call(base, "GET", f"/tasks/{tid}/graph")
    assert st == 200 and g["task"] == tid and g["turn"] == 1 and g["status"] == "done"
    assert g["children"] == 1 and g["children_done"] is True
    kid = next(a for a in g["agents"] if a["id"] == "root.1")
    assert kid["parent"] == "root" and kid["task"] == "Writer: write report.md" and kid["status"] == "done"
    assert kid["max_steps"] == 5 and kid["steps"] == 3 and kid["progress"] == 1.0
    assert g["files"] == ["report.md"]
    # one "progress" event per model step, labelled with the agent, carrying its budget
    events = call(base, "GET", f"/tasks/{tid}/events")[1]["events"]
    prog = [e for e in events if e["kind"] == "progress"]
    assert [(e["agent"], e["steps"], e["max_steps"]) for e in prog if e["agent"] == "root.1"] == \
        [("root.1", 1, 5), ("root.1", 2, 5), ("root.1", 3, 5)]
    assert any(e["agent"] == "root" for e in prog)
    # the same events are pushed on the SSE stream
    st, body, _ = raw(base, f"/tasks/{tid}/stream?once=1")
    lines = [json.loads(x[6:]) for x in body.decode().splitlines() if x.startswith("data: ")]
    assert any(e["kind"] == "progress" and e["agent"] == "root.1" for e in lines)


def test_graph_without_children_and_unknown_task(server, ws):
    base, _ = server(lambda: MockLLM())
    tid = call(base, "POST", "/tasks", {"task": "hi"})[1]["id"]
    finished(base, tid)
    g = call(base, "GET", f"/tasks/{tid}/graph")[1]
    assert g["children"] == 0 and g["children_done"] is False and [a["id"] for a in g["agents"]] == ["root"]
    assert call(base, "GET", "/tasks/0000000000/graph")[0] == 404


def test_file_link_serves_only_files_written_this_turn(server, ws):
    base, tid = run_swarm(server, ws)
    st, body, hdr = raw(base, f"/tasks/{tid}/file?path=report.md")
    assert st == 200 and body == b"# report\n" and hdr["Content-Type"].startswith("text/plain")
    assert "sandbox" in hdr["Content-Security-Policy"] and hdr["X-Content-Type-Options"] == "nosniff"
    for p in ("hello.txt", ".env", "../report.md", "%2Fetc%2Fpasswd", ""):
        assert raw(base, f"/tasks/{tid}/file?path={p}")[0] == 404, p


def test_graph_needs_auth_like_the_rest(server, ws):
    base, _ = server(lambda: MockLLM(), token="s3cret-token")
    tid = call(base, "POST", "/tasks", {"task": "x"}, {"Authorization": "Bearer s3cret-token"})[1]["id"]
    assert call(base, "GET", f"/tasks/{tid}/graph")[0] == 401
    assert raw(base, f"/tasks/{tid}/file?path=x")[0] == 401
    assert call(base, "GET", f"/tasks/{tid}/graph", headers={"Authorization": "Bearer s3cret-token"})[0] == 200


def test_chat_page_has_the_graph_and_new_strings():
    for k in ("chat.brand", "chat.thinking", "swarm.summary", "swarm.merged", "ask.write", "reason.category"):
        assert k in i18n.EN and i18n.FR[k] and i18n.FR[k] != i18n.EN[k], k
    assert 'id="swarm"' in CHAT_PAGE and 'id="thinking"' in CHAT_PAGE and "/graph" in CHAT_PAGE
    assert "prefers-reduced-motion" in CHAT_PAGE and ":focus-visible" in CHAT_PAGE


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
@pytest.mark.parametrize("lang", ["en", "fr"])
def test_approval_question_and_reason_are_human_and_translated(lang):
    d = getattr(i18n, lang.upper())
    js = ("const D=" + json.dumps(d) + ";\n"
          "function t(k,v){ let s=D[k]; if(s==null) return k; for(const n in (v||{})) s=s.split('{'+n+'}').join(v[n]); return s; }\n"
          "function tr(p,v){ const k=p+'.'+v; return D[k]!=null ? t(k) : String(v); }\n" + APPROVAL_JS + "\n"
          "console.log(JSON.stringify([askText({tool:'write_file',category:'write',args:{path:'report.md'}}),"
          "askText({tool:'spawn_agents',category:'delegate',args:{tasks:['a','b','c']}}),"
          "askText({tool:'web_fetch',category:'network',args:{url:'https://example.com/x'}}),"
          "askText({tool:'mystery',category:'send',args:{}}),"
          "reasonText(\"category default 'write: ask'\"), reasonText(\"tool rule 'shell: ask'\"),"
          "reasonText(\"category default 'send: ask'; --yolo ignored for 'send' (set it to allow in the file yourself)\"),"
          "reasonText('something else')]));")
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    if lang == "en":
        assert out[:4] == ["Allow writing report.md?", "Allow launching 3 sub-agents?",
                           "Allow fetching a page from example.com?", "Allow mystery (send)?"]
        assert out[4] == "Default for “write” actions: ask" and out[5] == "Rule for shell: ask"
        assert out[6].endswith("(--yolo does not apply to this category)")
    else:
        assert out[:4] == ["Autoriser l'écriture de report.md ?", "Autoriser le lancement de 3 sous-agents ?",
                           "Autoriser la lecture d'une page de example.com ?", "Autoriser mystery (envoi) ?"]
        assert out[4] == "Règle par défaut pour les actions « écriture » : demander"
        assert "--yolo ne s'applique pas" in out[6]
    assert out[7] == "something else"
