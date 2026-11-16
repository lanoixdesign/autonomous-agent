"""v0.6 "beginner-friendly": plain-language approvals and trace, translated server errors, provider auto-detection,
Simple / Expert display, "My files" (list / add / download), result downloads, Help page + tour, demo wording."""
import base64
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agent import i18n
from agent.harness_chat import CHAT_PAGE
from agent.harness_help import HELP_PAGE
from agent.harness_settings import SETTINGS_PAGE, WELCOME_PAGE
from agent.llm import MockLLM
from agent.loop import Budget
from agent.harness import NEVER_REMEMBER
from agent.swarm import SwarmConfig
from agent.theme import APPROVAL_JS
from agent.userconfig import KEY_PREFIXES, SettingsError, detect_provider

from test_harness import call, finished, pending, server  # noqa: F401  (fixture)
from test_settings_ui import app, csrf, post  # noqa: F401  (fixture)

REPO = Path(__file__).resolve().parent.parent
NODE = pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")


def raw(base, path, headers=None):
    req = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def b64(s: bytes) -> str:
    return base64.b64encode(s).decode()


# ------------------------------------------------------------------------- translated server errors
def test_every_settings_error_code_has_a_message_in_both_languages():
    src = (REPO / "agent" / "userconfig.py").read_text() + (REPO / "agent" / "harness.py").read_text()
    codes = set(re.findall(r'SettingsError\("([a-z_]+)"', src)) | set(re.findall(r'"code": "([a-z_]+)"', src))
    codes -= {"ok", "invalid", "missing", "format", "wrong_provider", "rate_limited", "unreachable", "error", "offline"}
    assert {"num_range", "bad_key", "ws_too_wide", "perm_protected", "locked", "csrf"} <= codes
    for c in codes:
        assert "srv." + c in i18n.EN and "srv." + c in i18n.FR, c
        assert i18n.EN["srv." + c] != i18n.FR["srv." + c], c
    e = SettingsError("num_range", field="max_tasks", lo=1, hi=16)
    assert isinstance(e, ValueError) and e.code == "num_range" and e.params == {"field": "max_tasks", "lo": "1", "hi": "16"}


def test_http_400_carries_a_stable_code_and_params(app):
    base, h, c = app()
    st, r = post(base, "/app/settings", {"max_tasks": 99})
    assert st == 400 and r["code"] == "num_range" and r["params"]["field"] == "max_tasks" and r["error"]
    st, r = post(base, "/app/providers", {"provider": "groq", "name": "g", "categories": ["text"], "key": "has space x"})
    assert st == 400 and r["code"] == "key_spaces"
    st, r = call(base, "POST", "/app/settings", {"ui_mode": "expert"})        # no CSRF token
    assert st == 403 and r["code"] == "csrf"
    # the pages translate them: errText() looks up srv.<code> and field labels
    assert 'tr("srv",b.code,v)' in SETTINGS_PAGE and "err.offline" in SETTINGS_PAGE


# ------------------------------------------------------------------------- provider auto-detection
def test_provider_is_detected_from_the_key_format(app):
    assert detect_provider("gsk_abc123") == "groq" and detect_provider(" sk-or-v1-xyz") == "openrouter"
    assert detect_provider("sk-proj-abc") == "openai" and detect_provider("sk-ant-abc") is None
    assert detect_provider("hello") is None and detect_provider("") is None
    base, h, c = app()
    v = call(base, "GET", "/app/settings")[1]
    assert v["key_prefixes"] == [list(p) for p in KEY_PREFIXES] and v["presets"]["groq"]["keys_url"].startswith("https://")
    r = post(base, "/app/providers/test", {"provider": "openai", "key": "gsk_0123456789abcdef"})[1]
    assert r == {"ok": False, "code": "wrong_provider", "detected": "groq"} or (r["code"] == "wrong_provider" and r["detected"] == "groq")
    for page in (WELCOME_PAGE, SETTINGS_PAGE):
        assert "key_prefixes" in page and "wiz.detected" in page


def test_wizard_has_demo_tile_provider_cards_and_step_by_step_guide():
    for k in ("wiz.demoTile", "wiz.orReal", "wiz.rec", "wiz.openSite"):
        assert f'"{k}"' in WELCOME_PAGE or f'data-i18n="{k}"' in WELCOME_PAGE, k
    assert WELCOME_PAGE.index('id="demo"') < WELCOME_PAGE.index('id="provs"')     # "Try without a key" comes first
    assert 'id="guide" open' in WELCOME_PAGE and 'target="_blank" rel="noopener noreferrer"' in WELCOME_PAGE
    for p in ("groq", "openai", "openrouter", "ollama"):
        for n in "1234":
            assert f"wiz.g.{p}.{n}" in i18n.EN and f"wiz.g.{p}.{n}" in i18n.FR
    assert "Essayer sans clé" in i18n.FR["wiz.demoTile"] and "gratuit" in i18n.FR["wiz.rec"]


# ------------------------------------------------------------------------- simple / expert, trace mode
def test_display_modes_are_validated_persisted_and_exposed(app, tmp_path):
    base, h, c = app()
    s = call(base, "GET", "/app/status")[1]
    assert s["ui_mode"] == "simple" and s["trace"] == "simple"                  # beginner defaults
    st, v = post(base, "/app/settings", {"ui_mode": "expert", "trace": "technical"})
    assert st == 200 and v["ui_mode"] == "expert" and v["trace"] == "technical"
    assert json.loads((tmp_path / "state" / "settings.json").read_text())["ui_mode"] == "expert"
    s = call(base, "GET", "/app/status")[1]
    assert s["ui_mode"] == "expert" and s["trace"] == "technical"
    for bad in ({"ui_mode": "hacker"}, {"trace": 3}):
        st, r = post(base, "/app/settings", bad)
        assert st == 400 and r["code"] == "bad_choice", bad


def test_settings_page_hides_expert_parts_in_simple_mode():
    assert 'class="simple"' in SETTINGS_PAGE and "body.simple .xp{display:none!important}" in SETTINGS_PAGE
    for sel in ('id="safety" class="card xp"', 'id="idc" class="card xp"', 'id="fadv" class="xp"',
                'id="flimd" class="xp"', 'id="newtok" class="grey xp"', 'href="#idc" class="xp"'):
        assert sel in SETTINGS_PAGE, sel
    assert 'name="uimode"' in SETTINGS_PAGE and 'name="trmode"' in SETTINGS_PAGE and 'id="bigtext"' in SETTINGS_PAGE
    tips = set(re.findall(r'data-tip="([^"]+)"', SETTINGS_PAGE))
    assert len(tips) >= 10 and all(k in i18n.EN and k in i18n.FR for k in tips)
    assert i18n.FR["set.workspace"] == "Dossier de travail" and i18n.EN["set.workspace"] == "Work folder"


# ------------------------------------------------------------------------- my files / downloads
def test_my_files_list_add_and_download(server, ws):
    base, h = server(lambda: MockLLM())
    (ws / "sub").mkdir()
    (ws / "sub" / "notes.txt").write_text("n")
    (ws / ".hidden").mkdir()
    (ws / ".hidden" / "x.txt").write_text("x")
    st, r = call(base, "GET", "/files")
    names = [f["path"] for f in r["files"]]
    assert st == 200 and r["available"] and "hello.txt" in names and "sub/notes.txt" in names
    assert ".env" not in names and not any(n.startswith(".hidden") for n in names)
    st, r = call(base, "POST", "/files", {"files": [{"name": "rapport été.txt", "content_b64": b64(b"bonjour")}]})
    assert st == 201 and r["saved"][0]["path"] == "rapport été.txt"
    st, r2 = call(base, "POST", "/files", {"files": [{"name": "rapport été.txt", "content_b64": b64(b"again")}]})
    assert st == 201 and r2["saved"][0]["path"] != "rapport été.txt"                 # never overwrites
    assert (ws / "rapport été.txt").read_bytes() == b"bonjour"
    if os.name != "nt":
        assert (ws / "rapport été.txt").stat().st_mode & 0o077 == 0
    q = urllib.parse.quote("rapport été.txt")
    st, body, hdr = raw(base, "/files/download?path=" + q)
    assert st == 200 and body == b"bonjour" and hdr["Content-Disposition"].startswith("attachment;")
    assert "filename*=UTF-8''" in hdr["Content-Disposition"] and "sandbox" in hdr["Content-Security-Policy"]
    assert raw(base, "/files/download?path=sub/notes.txt")[0] == 200


def test_my_files_refuses_escapes_hidden_and_symlinks(server, ws, tmp_path):
    base, h = server(lambda: MockLLM())
    (tmp_path / "outside.txt").write_text("secret")
    try:
        (ws / "link.txt").symlink_to(tmp_path / "outside.txt")
        (ws / "linkdir").symlink_to(tmp_path)
    except (OSError, NotImplementedError):
        pass
    for p in (".env", "../outside.txt", "link.txt", "linkdir/outside.txt", "/etc/passwd", "", "sub/../../outside.txt",
              "%2e%2e/outside.txt"):
        assert raw(base, "/files/download?path=" + p)[0] == 404, p
    names = [f["path"] for f in call(base, "GET", "/files")[1]["files"]]
    assert "link.txt" not in names and not any(n.startswith("linkdir") for n in names)
    assert call(base, "POST", "/files", {"files": [{"name": "../evil.txt", "content_b64": b64(b"x")}]})[0] == 201
    assert not (tmp_path / "evil.txt").exists()                                       # name sanitised, stays inside
    assert call(base, "POST", "/files", {"files": "nope"})[0] == 400


def test_my_files_need_auth(server, ws):
    base, h = server(lambda: MockLLM(), token="s3cret-token")
    assert call(base, "GET", "/files")[0] == 401
    assert raw(base, "/files/download?path=hello.txt")[0] == 401
    assert call(base, "POST", "/files", {"files": [{"name": "a.txt", "content_b64": b64(b"x")}]})[0] == 401
    st, body, _ = raw(base, "/files/download?path=hello.txt", {"Authorization": "Bearer s3cret-token"})
    assert st == 200 and body.startswith(b"hello world")


def test_result_file_can_be_downloaded(server, ws):
    script = [{"tool": "write_file", "args": {"path": "report.md", "content": "# r\n"}}, {"content": "done"}]
    base, h = server(lambda: MockLLM(list(script)))
    tid = call(base, "POST", "/tasks", {"task": "write it"})[1]["id"]
    ap = pending(base)[0]
    call(base, "POST", f"/approvals/{ap['id']}", {"decision": "approve"})
    finished(base, tid)
    st, body, hdr = raw(base, f"/tasks/{tid}/file?path=report.md&download=1")
    assert st == 200 and body == b"# r\n" and hdr["Content-Disposition"].startswith("attachment")
    assert raw(base, f"/tasks/{tid}/file?path=report.md")[2]["Content-Disposition"].startswith("inline")
    assert "download=1" in CHAT_PAGE and 'class="results"' in CHAT_PAGE or '"results"' in CHAT_PAGE


# ------------------------------------------------------------------------- demo wording
def test_demo_mode_is_named_demo_not_single_key(app):
    base, h, c = app()
    assert post(base, "/app/settings", {"demo": True})[0] == 200
    assert call(base, "GET", "/keys")[1]["mode"] == "demo"
    assert call(base, "GET", "/health")[1]["keys"]["mode"] == "demo"
    assert "keys.mode.demo" in i18n.EN and "dash.keysDemo" in i18n.FR


# ------------------------------------------------------------------------- help page, tour, chat home
def test_help_page_is_served_with_nav_in_both_languages(server):
    base, h = server(lambda: MockLLM())
    for lang, word in (("en", "Help"), ("fr", "Aide")):
        st, body, _ = raw(base, "/help?lang=" + lang)
        html = body.decode()
        assert st == 200 and f'<html lang="{lang}">' in html and 'data-nav="help"' in html
    assert 'href="/?tour=1"' in HELP_PAGE and "setBig" in HELP_PAGE
    assert i18n.EN["nav.help"] == "Help" and i18n.FR["nav.help"] == "Aide"


def test_chat_page_guides_the_first_task():
    for x in ('class="exgrid"', 'id="filesbtn"', 'id="filesp"', 'id="tour"', 'id="tournext"', 'class="lbl"'):
        assert x in CHAT_PAGE or x.replace('class="', '"') in CHAT_PAGE, x
    for ex in ("summarize", "email", "notes", "research", "plan", "translate"):
        for part in "tdp":
            assert f"ex.{ex}.{part}" in i18n.EN and f"ex.{ex}.{part}" in i18n.FR
    assert "tourDone" in CHAT_PAGE and "dragover" in CHAT_PAGE
    assert i18n.FR["card.allow"].endswith("Autoriser") and i18n.FR["card.refuse"].endswith("Refuser") and "card.tech" in i18n.EN


# ------------------------------------------------------------------------- plain language (JS)
def _run(lang, calls):
    d = getattr(i18n, lang.upper())
    js = ("const D=" + json.dumps(d) + ";\n"
          "function t(k,v){ let s=D[k]; if(s==null) return k; for(const n in (v||{})) s=s.split('{'+n+'}').join(v[n]); return s; }\n"
          "function tr(p,v,x){ const k=p+'.'+v; return D[k]!=null ? t(k,x) : String(v); }\n" + APPROVAL_JS + "\n"
          "console.log(JSON.stringify([" + ",".join(calls) + "]));")
    return json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)


@NODE
def test_plain_language_questions_in_both_languages():
    calls = ["askText({tool:'spawn_agents',category:'delegate',args:{tasks:['Chercheur: x','Analyste: y','Rédacteur: z']}})",
             "askText({tool:'write_file',category:'write',args:{path:'report.md'}})",
             "askText({agent:'root.2',tool:'shell',category:'shell',args:{command:'rm -rf /'}})",
             "plain('simple','read_file',{path:'notes.txt'},'root','read')",
             "plain('simple','web_search',{query:'prix'},'root','network')"]
    fr = _run("fr", calls)
    assert fr[0] == "L'agent veut créer 3 assistants pour vous aider : Chercheur, Analyste, Rédacteur"
    assert fr[1] == "L'agent veut écrire le fichier report.md"
    assert fr[2].startswith("Assistant 2 veut") and "rm -rf" not in fr[2]          # the raw command stays in the details
    en = _run("en", calls)
    assert en[1] == "The agent wants to write the file report.md" and "notes.txt" in en[3]
    assert not any("_" in s.split(" ")[0] for s in en + fr)                         # no raw tool names up front


@NODE
def test_unknown_tool_still_reads_like_a_sentence():
    out = _run("en", ["askText({tool:'mystery_tool',category:'send',args:{}})",
                      "askText({tool:'mystery_tool',category:'',args:{}})"])
    assert all(s.startswith("The agent wants to") for s in out), out


# ------------------------------------------------------------------------- safety invariants unchanged
def test_send_and_spend_can_still_never_be_remembered_or_allowed(app):
    assert {"send", "spend"} <= set(NEVER_REMEMBER)
    base, h, c = app()
    for cat in ("send", "spend"):
        st, r = post(base, "/app/settings", {"permissions": {cat: "allow"}})
        assert st == 400 and r["code"] == "perm_protected", r
    assert "card.safety" in CHAT_PAGE or "card.safety" in APPROVAL_JS
