"""v0.8.2: answers in the user's language (main agent, helpers, developer mode), malformed tool calls retried,
developer-mode confinement, `a && b` and `ls -R` in the sandbox, "tu" in French, the phone tab bar, and fixes
(Python template, Groq default model, dashboard key mode, swarm graph, masked keys after a restart)."""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agent import devmode, i18n, sandbox, theme
from agent.audit import AuditLog
from agent.llm import CALLER, PROVIDERS, LLMError, LLMReply, OpenAICompatible, is_tool_format_error
from agent.loop import FORMAT_NOTE, FORMAT_RETRIES, Budget
from agent.permissions import Permissions
from agent.swarm import SwarmConfig, usable_tools
from agent.tools import ToolError
from agent.tools import files as files_mod
from agent.tools import shell as shell_mod
from agent import userconfig

from test_settings_ui import app, call  # noqa: F401  (fixture)
from test_harness import finished

REPO = Path(__file__).resolve().parent.parent
ALLOW = Permissions.from_dict({"defaults": {"delegate": "allow", "write": "allow", "read": "allow"}})
BIG = Budget(max_steps=30, max_tool_calls=30, max_tokens=10 ** 7)


def say(text):
    return LLMReply({"role": "assistant", "content": text}, 1, 1)


def call_tool(name, args, cid="c1"):
    return LLMReply({"role": "assistant", "content": None, "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}, 1, 1)


# ------------------------------------------------------------------------- 1. language
@pytest.mark.parametrize("text,lang", [
    ("Utilise trois sous-agents en parallèle avec spawn_agents", "fr"),
    ("ajoute un bouton qui change la couleur", "fr"),
    ("Écris un poème", "fr"),
    ("Summarize notes.txt in 3 lines", "en"),
    ("Write a haiku about the sea", "en"),
    ("Continue.", None), ("ok", None), ("python main.py", None),
])
def test_detect_lang(text, lang):
    assert i18n.detect_lang(text) == lang
    assert i18n.detect_lang(text, "fr") == (lang or "fr")


class EchoLLM:
    def __init__(self):
        self.systems = []

    def chat(self, messages, tools=None):
        self.systems.append(messages[0]["content"])
        return say("ok")


def test_main_agent_answers_in_the_language_of_the_request(make_agent):
    llm = EchoLLM()
    agent = make_agent(llm)
    agent.ui_lang = "en"
    agent.run("Résume le fichier hello.txt pour moi")
    assert agent.lang == "fr" and "the user writes in French" in llm.systems[-1] and '"tu"' in llm.systems[-1]
    agent.run("Continue.")                       # unclear: keeps French
    assert agent.lang == "fr" and "in French" in llm.systems[-1]
    agent.run("Now write it in English please")
    assert agent.lang == "en" and "the user writes in English" in llm.systems[-1]
    assert sum(m["role"] == "system" for m in agent.messages) == 1


def test_unclear_first_message_uses_the_app_language(make_agent):
    llm = EchoLLM()
    agent = make_agent(llm)
    agent.ui_lang = "fr"
    agent.run("ok")
    assert agent.lang == "fr" and "in French" in llm.systems[-1]


class SpawnLLM:
    """Root spawns one helper (with the given allowed_tools), the helper writes a file, root answers."""

    def __init__(self, allowed=None, child_path="projects/site/a.txt"):
        self.allowed, self.child_path = allowed, child_path
        self.child_systems, self.child_tools, self.child_obs = [], [], []

    def chat(self, messages, tools=None):
        task = messages[1]["content"]
        if "Codeur" not in task:
            if not any(m["role"] == "tool" for m in messages):
                args = {"task": "Codeur: écris le fichier"}
                if self.allowed is not None:
                    args["allowed_tools"] = self.allowed
                return call_tool("spawn_agent", args, "s1")
            return say("fini")
        self.child_systems.append(messages[0]["content"])
        self.child_tools.append(sorted(t["function"]["name"] for t in tools or []))
        obs = [m["content"] for m in messages if m["role"] == "tool"]
        if not obs:
            return call_tool("write_file", {"path": self.child_path, "content": "x"}, "w1")
        self.child_obs.append(obs[-1])
        return say("écrit")


def test_helpers_inherit_language_rules_and_get_tools_with_empty_allowed_tools(make_agent, ws):
    llm = SpawnLLM(allowed=[])
    agent = make_agent(llm, perms=ALLOW, budget=BIG, swarm=SwarmConfig(max_parallel=1, max_children=3))
    agent.child_rules = devmode.child_rules("site", "fr")
    res = agent.run("Crée un fichier dans le projet, merci")
    assert res.answer == "fini"
    assert "in French" in llm.child_systems[0] and "projects/site/" in llm.child_systems[0]
    assert "write_file" in llm.child_tools[0] and "read_file" in llm.child_tools[0]   # [] = all of the parent's
    assert (ws / "projects" / "site" / "a.txt").read_text() == "x"


def test_usable_tools(make_agent):
    agent = make_agent(EchoLLM(), swarm=SwarmConfig())
    assert usable_tools(agent, None) is None
    assert usable_tools(agent, []) is None and usable_tools(agent, "") is None
    assert usable_tools(agent, ["nope", "made_up"]) is None
    assert usable_tools(agent, ["read_file", "nope"]) == ["read_file"]
    assert usable_tools(agent, "read_file, list_files") == ["read_file", "list_files"]
    schema = {t["function"]["name"]: t["function"]["parameters"] for t in agent.tool_schemas()}
    assert "null" in schema["spawn_agents"]["properties"]["max_steps"]["type"]      # null is "not given"
    assert "null" in schema["spawn_agents"]["properties"]["allowed_tools"]["type"]


def test_dev_rules_follow_the_language_and_never_mention_an_ide_preview():
    fr, en = devmode.rules("site", "web", "fr"), devmode.rules("site", "web", "en")
    assert "Codeur:" in fr and "Testeur:" in fr and "onglet Dév" in fr and "👁 Aperçu" in fr
    assert "Coder:" in en and "Tester:" in en and "Dev tab" in en and "👁 Preview" in en
    for r in (fr, en):
        assert "Developer page -> Preview" not in r and "button in the IDE" not in r
    assert "ls -R projects/site" in devmode.child_rules("site")


# ------------------------------------------------------------------------- 2. malformed tool calls
class FlakyLLM:
    def __init__(self, fails, err=None):
        self.fails, self.calls, self.temps = fails, [], []
        self.err = err or LLMError('HTTP 400 from groq: {"error":{"message":"Failed to call a function. Please '
                                   'adjust your prompt.","type":"invalid_request_error","code":"tool_use_failed"}}',
                                   status=400, code="tool_use_failed")

    def chat(self, messages, tools=None):
        self.calls.append([dict(m) for m in messages])
        self.temps.append((CALLER.get() or {}).get("temperature"))
        if len(self.calls) <= self.fails:
            raise self.err
        return say("réponse")


def test_malformed_tool_call_is_retried_with_a_note(make_agent):
    events = []
    llm = FlakyLLM(2)
    agent = make_agent(llm, on_event=lambda k, d: events.append((k, d)))
    res = agent.run("Fais quelque chose pour moi")
    assert res.stop_reason == "final" and res.answer == "réponse"
    retries = [d for k, d in events if k == "retry"]
    assert [r["attempt"] for r in retries] == [1, 2] and retries[0]["max"] == FORMAT_RETRIES
    note = llm.calls[1][-1]                                                       # corrective note on the retry
    assert note["role"] == "system" and note["content"].startswith(FORMAT_NOTE)
    assert "The provider said: Failed to call a function" in note["content"]
    assert llm.temps[0] is None and llm.temps[1] is not None and llm.temps[2] == 0.0
    assert not any(FORMAT_NOTE in str(m.get("content")) for m in agent.messages)  # not kept in the history
    log = (Path(agent.audit.path)).read_text()
    assert '"llm_retry"' in log


def test_retries_are_limited_and_other_errors_are_not_retried(make_agent):
    llm = FlakyLLM(99)
    res = make_agent(llm).run("go")
    assert res.stop_reason == "llm_error" and len(llm.calls) == FORMAT_RETRIES + 1
    other = FlakyLLM(99, LLMError("HTTP 400: context too long", status=400))
    res = make_agent(other).run("go")
    assert res.stop_reason == "llm_error" and len(other.calls) == 1


def test_tool_format_errors_are_recognised():
    assert is_tool_format_error(LLMError("x", status=400, code="tool_use_failed"))
    assert is_tool_format_error(LLMError("HTTP 400: Tool choice is none, but model called a tool", status=400))
    assert not is_tool_format_error(LLMError("HTTP 429", status=429))
    assert not is_tool_format_error(ValueError("tool_use_failed"))


def test_openai_client_tags_tool_use_failed_and_takes_the_retry_temperature():
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body["temperature"])
            out = json.dumps({"error": {"message": "Failed to call a function.", "code": "tool_use_failed"}}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = OpenAICompatible(f"http://127.0.0.1:{srv.server_address[1]}", "m", "k", retries=0)
        tok = CALLER.set({"temperature": 0.0})
        try:
            with pytest.raises(LLMError) as e:
                c.chat([{"role": "user", "content": "hi"}])
        finally:
            CALLER.reset(tok)
        assert e.value.code == "tool_use_failed" and e.value.status == 400 and seen == [0.0]
    finally:
        srv.shutdown()


# ------------------------------------------------------------------------- 3. developer-mode confinement
def test_write_prefix_confines_write_and_edit(ctx, ws):
    import dataclasses
    c = dataclasses.replace(ctx, write_prefix="projects/site/")
    files_mod._write(c, {"path": "projects/site/index.html", "content": "<p>hi</p>"})
    with pytest.raises(ToolError, match="developer mode"):
        files_mod._write(c, {"path": "stray.txt", "content": "x"})
    with pytest.raises(ToolError, match="developer mode"):
        files_mod._edit(c, {"path": "hello.txt", "old": "hello", "new": "bye"})
    with pytest.raises(ToolError, match="developer mode"):
        files_mod._write(c, {"path": "projects/site/../other.txt", "content": "x"})
    assert not (ws / "stray.txt").exists() and (ws / "projects" / "site" / "index.html").exists()


def test_write_prefix_confines_sandbox_commands(ctx, ws):
    import dataclasses
    (ws / "projects" / "site").mkdir(parents=True)
    c = dataclasses.replace(ctx, write_prefix="projects/site/", sandbox=lambda: True)
    assert shell_mod._shell(c, {"command": "touch projects/site/a.txt"}).startswith("exit=0")
    for cmd in ("touch b.txt", "mkdir junk", "rm hello.txt", "cp hello.txt copy.txt", "mv hello.txt projects/site/"):
        with pytest.raises(ToolError, match="developer mode"):
            shell_mod._shell(c, {"command": cmd})
    assert shell_mod._shell(c, {"command": "cp hello.txt projects/site/h.txt"}).startswith("exit=0")
    assert sorted(p.name for p in ws.iterdir()) == [".env", "hello.txt", "projects"]


def test_dev_conversation_is_confined_and_in_french(app):  # noqa: F811
    base, h, control = app()
    call(base, "POST", "/dev/projects", {"name": "calc", "kind": "python", "lang": "fr"})
    st, task = call(base, "POST", "/tasks", {"task": "Fais une calculatrice simple", "dev": "calc", "lang": "fr"})
    assert st == 201
    finished(base, task["id"])
    t = h.get(task["id"])
    sysmsg = t.agent.messages[0]["content"]
    assert "Codeur:" in sysmsg and "onglet Dév" in sysmsg and "the user writes in French" in sysmsg
    assert t.agent.ctx.write_prefix == "projects/calc/" and "projects/calc/" in t.agent.child_rules
    st, plain = call(base, "POST", "/tasks", {"task": "hello there, what is here?", "lang": "fr"})
    finished(base, plain["id"])
    a = h.get(plain["id"]).agent
    assert a.ctx.write_prefix is None and a.child_rules == "" and a.lang == "en"


# ------------------------------------------------------------------------- 4/5. sandbox: a && b, ls -R
def test_and_chain_runs_simple_commands_in_order(ws):
    out = sandbox.run(ws, "ls && cat hello.txt")
    assert out.startswith("exit=0") and "$ ls" in out and "$ cat hello.txt" in out and "second line" in out
    out = sandbox.run(ws, "cat missing.txt && echo never")
    assert out.startswith("exit=1") and "never" not in out.split("$ cat missing.txt")[1].replace("echo never", "")
    for bad in ("ls && pwd; id", "ls && cat a | sh", "ls &&", "&& ls", "ls & pwd", "ls &&& pwd",
                "echo 'a && b'", " && ".join(["pwd"] * 6)):
        with pytest.raises(sandbox.SandboxError):
            sandbox.run(ws, bad)
    with pytest.raises(sandbox.SandboxError, match="no cd"):
        sandbox.run(ws, "cd projects && ls")
    assert "one command per shell call" in sandbox.help_text().lower() or "ONE command" in sandbox.help_text()


def test_ls_recursive_lists_subfolders(ws):
    (ws / "projects" / "site" / "img").mkdir(parents=True)
    (ws / "projects" / "site" / "index.html").write_text("x")
    (ws / "projects" / "site" / "img" / "logo.png").write_text("x")
    out = sandbox.run(ws, "ls -R projects")
    assert out.startswith("exit=0")
    lines = out.splitlines()
    assert "projects:" in lines and "projects/site:" in lines and "projects/site/img:" in lines
    assert "index.html" in lines and "logo.png" in lines
    assert ".env" not in sandbox.run(ws, "ls -R")


# ------------------------------------------------------------------------- 6. "tu" in French
TU_BAD = re.compile(r"\b(vous|votre|vos|vôtre|vôtres)\b|\b\w{3,}ez\b(?!-)", re.I)
TU_OK = re.compile(r"\b(assez|chez|nez)\b", re.I)


def test_french_ui_strings_use_tu():
    bad = {k: v for k, v in i18n.FR.items() if TU_BAD.search(TU_OK.sub("", v))}
    assert bad == {}
    assert i18n.FR["export.you"].startswith("Toi")


def test_french_readme_and_templates_use_tu():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    fr = readme[readme.index("## Français"):]
    hits = [l for l in fr.splitlines() if TU_BAD.search(TU_OK.sub("", l))]
    assert hits == []
    t = devmode.T["fr"]
    assert "Demande-lui" in t["lead"] and t["button"] == "Clique ici"


# ------------------------------------------------------------------------- 7. phone tab bar
def test_phone_tab_bar_shows_every_tab_without_scrolling():
    # v0.9.2: the top tab bar became a left sidebar; on a phone it is a drawer listing every destination
    css = theme.NAV_CSS
    mobile = css[css.index("@media (max-width:760px)"):]
    assert "html.sn-open .sidenav{transform:none}" in mobile and ".snmenu{display:inline-flex}" in mobile
    side = theme.sidebar()
    for k in ("chat", "dashboard", "dev", "settings", "connect", "help"):
        assert f'data-nav="{k}"' in side, k


# ------------------------------------------------------------------------- 8. leftovers
def test_python_template_greets_in_one_language():
    fr, en = devmode.template("python", "X", "fr"), devmode.template("python", "X", "en")
    assert 'f"Bonjour, {name} !"' in fr["main.py"] and 'greet("tout le monde")' in fr["main.py"]
    assert '"Bonjour, Ada !"' in fr["test_main.py"] and "world" not in fr["main.py"]
    assert 'f"Hello, {name}!"' in en["main.py"] and 'greet("world")' in en["main.py"]
    assert '"Hello, Ada!"' in en["test_main.py"]


def test_python_template_tests_pass(tmp_path):
    import subprocess
    import sys
    for lang in ("fr", "en"):
        d = tmp_path / lang
        d.mkdir()
        for name, text in devmode.template("python", "X", lang).items():
            (d / name).write_text(text, encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "unittest", "-q"], cwd=d, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_groq_default_model_is_gpt_oss_20b():
    assert PROVIDERS["groq"]["model"] == "openai/gpt-oss-20b"
    assert userconfig.PRESETS["groq"]["model"] == "openai/gpt-oss-20b"


def test_dashboard_names_settings_keys():
    from agent.harness_page import PAGE
    assert 'settings:"keys.mode.settings"' in PAGE
    assert i18n.FR["keys.mode.settings"] == "clés des Réglages" and "keys.mode.settings" in i18n.EN


def _spawn(t, child, status="running"):
    t.on_audit({"event": "spawn", "agent": "root", "child": child, "child_depth": 1, "task": "Chercheur: x",
                "budget": {"max_steps": 4}})
    if status != "running":
        t.on_audit({"event": "child_done", "agent": child, "parent": "root", "stop_reason": status, "result": "r"})


def test_graph_counts_failed_helpers_and_keeps_earlier_turns():
    from agent.harness import Task
    t = Task("go")
    t.new_turn("go")
    _spawn(t, "root.1", "final")
    _spawn(t, "root.2", "llm_error")
    g = t.graph()
    assert g["failed"] == 1 and g["children"] == 2
    t.set_status("stopped")
    t.new_turn("Continue.")                               # a rerun: the earlier helpers stay in the graph
    g = t.graph()
    ids = {a["id"]: a for a in g["agents"]}
    assert "t1:root.1" in ids and "t1:root.2" in ids and ids["t1:root.1"]["earlier"] and ids["t1:root.1"]["turn"] == 1
    assert g["children"] == 2 and g["children_now"] == 0 and not g["children_done"]
    _spawn(t, "root.1", "final")                          # same id in the new turn: no clash
    g = t.graph()
    assert g["children"] == 3 and g["children_now"] == 1 and g["children_done"]
    from agent.harness_chat import CHAT_PAGE
    assert "swarm.mergedFail" in CHAT_PAGE and "swarm.earlier" in CHAT_PAGE


class _Store:
    def __init__(self):
        self.rows, self.events = {}, {}

    def put(self, kind, key, rec):
        self.rows[(kind, key)] = json.loads(json.dumps(rec))

    def add_event(self, tid, seq, ev):
        self.events.setdefault(tid, []).append(json.loads(json.dumps(ev)))


def test_masked_key_survives_a_restart_in_events_and_graph():
    from agent.harness import Task
    st = _Store()
    t = Task("go", st)
    t.new_turn("go")
    _spawn(t, "root.1")
    t.on_progress("root.1", 1, 4, {"key": "Groq perso", "key_mask": "gsk_…AB12", "key_task": "research",
                                   "key_match": True})
    t.save()
    ev = [e for e in st.events[t.id] if e["kind"] == "progress"][-1]
    assert ev["pool"] == "Groq perso" and ev["pool_mask"] == "gsk_…AB12"
    rec = st.rows[("tasks", t.id)]
    assert "***REDACTED***" not in json.dumps(rec["agents"])
    back = Task.restore(rec, st.events[t.id], None)
    a = next(x for x in back.graph()["agents"] if x["id"] == "root.1")
    assert a["key"] == "Groq perso" and a["key_mask"] == "gsk_…AB12" and a["keys"] == ["Groq perso"]
    old_agent = {k: v for k, v in rec["agents"][1].items() if not k.startswith("pool")}
    old = dict(rec, agents=[dict(old_agent, key="***REDACTED***", key_mask="***REDACTED***")])
    a = next(x for x in Task.restore(old, [], None).graph()["agents"] if x["id"] == "root.1")
    assert a["key"] is None and a["key_mask"] is None       # history saved before 0.8.2: shown without a key


def test_retry_event_has_plain_text_in_both_languages():
    assert i18n.FR["trace.retry"] == "Le modèle a mal formé une action, je réessaie…"
    assert "retrying" in i18n.EN["trace.retry"]
    from agent.harness_chat import CHAT_PAGE
    from agent.harness_page import PAGE
    assert 'e.kind==="retry"' in CHAT_PAGE and 'e.kind==="retry"' in PAGE
    assert 'e.event==="llm_retry") return null' in CHAT_PAGE          # no raw "llm_retry" line in the chat
