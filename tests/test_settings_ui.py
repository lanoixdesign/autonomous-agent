"""v0.5 "no terminal": Settings page API (keys per category, limits, failover, test), local-only + CSRF,
safeguards, live apply, restart / quit, first-run wizard, navigation, collapsible work trace."""
import json
import os
import re
import shutil
import stat
import subprocess
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agent import cli, remote
from agent.harness import Harness, make_server
from agent.harness_chat import CHAT_PAGE
from agent.harness_connect import CONNECT_PAGE
from agent.harness_page import PAGE
from agent.harness_settings import SETTINGS_PAGE, WELCOME_PAGE
from agent.llm import MockLLM, SwitchLLM
from agent.loop import Agent, Budget
from agent.permissions import Permissions
from agent.store import Store
from agent.tools import default_registry
from agent.userconfig import (RESTART_CODE, AppControl, SecretStore, UserConfig, apply_permissions,
                              apply_startup, key_format_ok)

from test_harness import call, finished, wait_for

SECRET = "sk-live-0123456789abcdefSECRET"


# ------------------------------------------------------------------------- a fake OpenAI-compatible provider
class FakeProvider:
    def __init__(self):
        self.auth: list[str] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                ok = self.headers.get("Authorization") == "Bearer " + SECRET
                self._json(200 if ok else 401, {"data": [{"id": "m1"}, {"id": "m2"}]} if ok else {"error": "bad key"})

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                a = self.headers.get("Authorization") or ""
                outer.auth.append(a)
                self._json(200, {"choices": [{"message": {"role": "assistant", "content": "answer from " + a[-6:]}}],
                                 "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/v1"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def fake():
    f = FakeProvider()
    yield f
    f.close()


@pytest.fixture
def app(ctx, tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_REMOTE_SETTINGS", raising=False)
    monkeypatch.delenv("AGENT_KEY_TEST", raising=False)
    started = []

    def start(token=None, remote_mode=False, prober=None):
        state = tmp_path / "state"
        cfg = UserConfig(state)
        sec = SecretStore(state / "secrets.json", use_keyring=False)
        perms = Permissions()
        control = AppControl(cfg, sec, perms=perms, prober=prober, home=str(state))

        def factory(task, audit, confirm, cancel, on_event):
            return Agent(SwitchLLM(control, "text", MockLLM), default_registry(enable_web=False, enable_github=False),
                         perms, audit, ctx, Budget(), confirm=confirm, on_event=on_event, cancel=cancel)
        store = Store(state / "harness.sqlite3")
        h = Harness(factory, state / "audit.jsonl", approval_timeout=5, workspace=ctx.workspace, store=store,
                    scheduler_tick=None)
        auth = remote.Auth(token, remote=remote_mode)
        control.h, control.auth, h.control = h, auth, control
        control.boot = {"workspace": str(ctx.workspace), "max_tasks": h.max_tasks,
                        "remote": {"enabled": remote_mode, "tunnel": "none", "public_url": ""}}
        srv = make_server(h, "127.0.0.1", 0, token, warn=lambda m: None, remote_mode=remote_mode, auth=auth)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append((srv, h, store))
        return f"http://127.0.0.1:{srv.server_address[1]}", h, control

    yield start
    for srv, h, store in started:
        h.shutdown()
        srv.shutdown()
        srv.server_close()
        store.close()


def csrf(base, headers=None):
    st, s = call(base, "GET", "/app/status", headers=headers)
    assert st == 200, s
    return s["csrf"]


def post(base, path, body=None, headers=None):
    hd = {"X-CSRF-Token": csrf(base, headers), **(headers or {})}
    return call(base, "POST", path, body or {}, headers=hd)


def raw(base, path):
    with urllib.request.urlopen(base + path, timeout=10) as r:
        return r.read().decode()


# ------------------------------------------------------------------------- secrets
def test_secret_store_is_private_and_never_in_repr(tmp_path):
    s = SecretStore(tmp_path / "d" / "secrets.json", use_keyring=False)
    s.set("a1", SECRET)
    assert s.get("a1") == SECRET and s.backend == "file" and SECRET not in repr(s)
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / "d" / "secrets.json").stat().st_mode) == 0o600
    assert SecretStore(tmp_path / "d" / "secrets.json", use_keyring=False).get("a1") == SECRET   # persisted
    s.delete("a1")
    assert s.get("a1") is None and SECRET not in (tmp_path / "d" / "secrets.json").read_text()


def test_key_format_check():
    assert key_format_ok("groq", "gsk_abcdefghijkl") and not key_format_ok("groq", "sk-abcdefghijkl")
    assert not key_format_ok("openai", "sk- with space") and key_format_ok("custom", "anything-long-enough")


# ------------------------------------------------------------------------- keys from the UI
def test_saved_key_is_masked_everywhere_and_never_logged(app, fake, tmp_path):
    base, h, c = app()
    st, p = post(base, "/app/providers", {"provider": "custom", "name": "fake", "base_url": fake.url, "model": "m1",
                                           "categories": ["text", "code"], "key": SECRET,
                                           "limits": {"requests_per_day": 50}})
    assert st == 201, p
    assert p["key"] == "sk-l••••CRET" and p["has_key"] and SECRET not in json.dumps(p)
    st, lst = call(base, "GET", "/app/providers")
    assert st == 200 and SECRET not in json.dumps(lst) and lst["providers"][0]["usage"]["requests_per_day"]["limit"] == 50
    for path in ("/keys", "/health", "/usage", "/app/settings"):
        assert SECRET not in json.dumps(call(base, "GET", path)[1]), path
    tid = call(base, "POST", "/tasks", {"task": "hi"})[1]["id"]
    assert finished(base, tid)["result"] == "answer from SECRET"
    state = tmp_path / "state"
    assert SECRET in (state / "secrets.json").read_text()
    for f in ("providers-ui.json", "settings.json", "audit.jsonl"):
        if (state / f).exists():
            assert SECRET not in (state / f).read_text(), f
    assert SECRET.encode() not in b"".join(p.read_bytes() for p in state.glob("harness.sqlite3*"))
    audit = (state / "audit.jsonl").read_text()
    assert '"settings_key_saved"' in audit


def test_keys_apply_live_edit_delete_and_failover(app, fake):
    base, h, c = app()
    # no key yet: the fallback (mock) answers
    t0 = call(base, "POST", "/tasks", {"task": "hello"})[1]["id"]
    assert finished(base, t0)["result"].startswith("[mock]")
    st, a = post(base, "/app/providers", {"provider": "custom", "name": "A", "base_url": fake.url, "model": "m1",
                                           "categories": ["text"], "key": SECRET, "limits": {"requests_per_day": 1}})
    assert st == 201
    st, b = post(base, "/app/providers", {"provider": "custom", "name": "B", "base_url": fake.url, "model": "m1",
                                           "categories": ["text"], "key": "sk-other-key-000000BBBBBB"})
    assert st == 201
    # same conversation, next message: the saved key is used without any restart
    assert call(base, "POST", f"/tasks/{t0}/messages", {"text": "again"})[0] == 202
    assert finished(base, t0)["result"] == "answer from SECRET"
    # key A reached its daily limit: key B takes over (failover, limit never exceeded)
    t1 = call(base, "POST", "/tasks", {"task": "third"})[1]["id"]
    assert finished(base, t1)["result"] == "answer from BBBBBB"
    assert fake.auth == ["Bearer " + SECRET, "Bearer sk-other-key-000000BBBBBB"]
    # order: B first now
    st, r = post(base, "/app/providers/order", {"ids": [b["id"], a["id"]]})
    assert st == 200 and [p["name"] for p in r["providers"]] == ["B", "A"]
    assert [e.name for e in c.router.entries] == ["B", "A"]
    # edit without a key keeps the secret; with one replaces it
    st, e = post(base, f"/app/providers/{a['id']}", {"model": "m2"})
    assert st == 200 and e["model"] == "m2" and c.secrets.get(a["id"]) == SECRET
    # delete both: back to the fallback
    for p in (a, b):
        assert post(base, f"/app/providers/{p['id']}/delete")[0] == 200
    assert c.secrets.get(a["id"]) is None and c.router.entries == []
    t2 = call(base, "POST", "/tasks", {"task": "bye"})[1]["id"]
    assert finished(base, t2)["result"].startswith("[mock]")


def test_validation_errors(app):
    base, h, c = app()
    assert post(base, "/app/providers", {"provider": "groq", "name": "g"})[0] == 400          # key required
    assert post(base, "/app/providers", {"provider": "nope", "key": "x" * 20})[0] == 400
    st, r = post(base, "/app/providers", {"provider": "groq", "key": "gsk_" + "a" * 20, "limits": {"cost_per_day": 1}})
    assert st == 400 and "price" in r["error"]
    assert post(base, "/app/providers", {"provider": "groq", "key": "gsk_" + "a" * 20, "limits": {"bogus": 1}})[0] == 400
    assert post(base, "/app/providers", {"provider": "ollama", "name": "local"})[0] == 201    # no key needed
    assert post(base, "/app/providers/abcdef/delete")[0] == 404


def test_key_test_is_lightweight_and_mock_safe(app, fake, monkeypatch):
    base, h, c = app()
    st, r = post(base, "/app/providers/test", {"provider": "custom", "base_url": fake.url, "key": SECRET})
    assert st == 200 and r["ok"] and r["code"] == "ok" and r["models"] == 2
    r = post(base, "/app/providers/test", {"provider": "custom", "base_url": fake.url, "key": "sk-wrong-000000000"})[1]
    assert not r["ok"] and r["code"] == "invalid"
    assert fake.auth == []                                   # /models only: no completion, no tokens spent
    assert post(base, "/app/providers/test", {"provider": "groq", "key": ""})[1]["code"] == "missing"
    assert post(base, "/app/providers/test", {"provider": "groq", "key": "sk-notgroq123456"})[1]["code"] == "format"
    monkeypatch.setenv("AGENT_KEY_TEST", "offline")
    assert post(base, "/app/providers/test", {"provider": "groq", "key": "gsk_" + "b" * 20})[1] == {"ok": True, "code": "offline"}
    pid = post(base, "/app/providers", {"provider": "custom", "name": "f", "base_url": fake.url, "model": "m",
                                        "key": SECRET})[1]["id"]
    monkeypatch.delenv("AGENT_KEY_TEST")
    assert post(base, f"/app/providers/{pid}/test")[1]["code"] == "ok"


# ------------------------------------------------------------------------- who may change settings
def test_settings_are_local_only_and_csrf_protected(app):
    base, h, c = app()
    st, r = call(base, "POST", "/app/settings", {"demo": True})
    assert st == 403 and r.get("csrf")                                     # no CSRF token
    st, r = call(base, "POST", "/app/settings", {"demo": True}, headers={"X-CSRF-Token": "x" * 40})
    assert st == 403 and r.get("csrf")
    assert post(base, "/app/settings", {"demo": True})[0] == 200
    relayed = {"X-Forwarded-For": "203.0.113.9"}                              # came through a proxy / tunnel
    st, s = call(base, "GET", "/app/status", headers=relayed)
    assert st == 200 and s["editable"] is False
    assert call(base, "GET", "/app/settings", headers=relayed)[1].get("locked")
    assert call(base, "GET", "/app/providers", headers=relayed)[0] == 403
    st, r = call(base, "POST", "/app/settings", {"demo": False}, headers={**relayed, "X-CSRF-Token": s["csrf"]})
    assert st == 403 and r.get("locked")


def test_remote_settings_need_env_sign_in_and_csrf(app, monkeypatch):
    token = "t" * 32
    base, h, c = app(token=token, remote_mode=True)
    relayed = {"X-Forwarded-For": "203.0.113.9"}
    assert call(base, "GET", "/app/status", headers=relayed)[0] == 401                # not signed in
    signed = {**relayed, "Authorization": "Bearer " + token}
    assert call(base, "GET", "/app/status", headers=signed)[1]["editable"] is False   # signed in, env not set
    monkeypatch.setenv("AGENT_REMOTE_SETTINGS", "1")
    s = call(base, "GET", "/app/status", headers=signed)[1]
    assert s["editable"] is True and s["remote_settings"] is True
    assert call(base, "POST", "/app/settings", {"demo": True}, headers=signed)[0] == 403          # CSRF still required
    assert call(base, "POST", "/app/settings", {"demo": True}, headers={**signed, "X-CSRF-Token": s["csrf"]})[0] == 200
    assert call(base, "GET", "/app/settings", headers=relayed)[0] == 401


# ------------------------------------------------------------------------- settings
def test_send_and_spend_never_auto_approved(app):
    base, h, c = app()
    for cat in ("send", "spend"):
        st, r = post(base, "/app/settings", {"permissions": {cat: "allow"}})
        assert st == 400 and "never" in r["error"]
    st, v = post(base, "/app/settings", {"permissions": {"write": "deny", "spend": "ask"}})
    assert st == 200 and c.perms.defaults["write"] == "deny" and c.perms.defaults["spend"] == "ask"
    assert v["permissions"]["protected"] == ["send", "spend"]
    p = Permissions()
    apply_permissions(p, UserConfig(c.cfg.dir))
    assert p.defaults["write"] == "deny"
    c.cfg.data["permissions"] = {"send": "allow"}                 # hand-edited file: still ignored
    apply_permissions(p, c.cfg)
    assert p.defaults["send"] == "ask"


def test_settings_apply_live_or_flag_a_restart(app, tmp_path):
    base, h, c = app()
    st, v = post(base, "/app/settings", {"approval_timeout": 42, "lang": "fr", "currency": "EUR"})
    assert st == 200 and h.approvals.timeout == 42 and h.lang == "fr" and v["restart_needed"] == []
    st, v = post(base, "/app/settings", {"max_tasks": 7, "workspace": str(tmp_path / "newws"),
                                          "remote": {"enabled": True, "tunnel": "tailscale"}})
    assert st == 200 and sorted(v["restart_needed"]) == ["max_tasks", "remote", "workspace"]
    assert h.max_tasks == 4                                        # not applied until the restart
    saved = UserConfig(c.cfg.dir)
    assert saved.get("max_tasks") == 7 and saved.get("remote")["tunnel"] == "tailscale" and saved.get("lang") == "fr"
    if os.name != "nt":
        assert stat.S_IMODE((c.cfg.dir / "settings.json").stat().st_mode) == 0o600
    for bad in ({"max_tasks": 0}, {"approval_timeout": 1}, {"workspace": "relative/path"}, {"workspace": "/"},
                {"remote": {"tunnel": "ngrok"}}, {"lang": "de"}, {"idc": {"vitality": -1}}, {"idc": {"nope": 1}}):
        assert post(base, "/app/settings", bad)[0] == 400, bad
    st, v = post(base, "/app/settings", {"idc": {"enabled": True, "vitality": 80, "stall_limit": 2}})
    assert st == 200 and h.idc_config.vitality == 80 and h.settings["idc"] is True and v["idc"]["stall_limit"] == 2
    # the saved settings feed the next start (flags typed on the command line win)
    args = type("A", (), {"lang": "en", "_lang_explicit": False, "approval_timeout": 300.0, "max_tasks": 4,
                          "state_dir": str(c.cfg.dir), "workspace": "."})()
    apply_startup(args, saved, cli.SERVE_DEFAULTS)
    assert (args.lang, args.approval_timeout, args.max_tasks, args.workspace) == ("fr", 42, 7, str((tmp_path / "newws").resolve()))


def test_first_run_wizard_and_demo_mode(app):
    base, h, c = app()
    s = call(base, "GET", "/app/status")[1]
    assert s["first_run"] is True and s["mode"] == "demo" and s["editable"] is True
    assert post(base, "/app/setup", {"lang": "fr"})[1]["first_run"] is True
    s = post(base, "/app/setup", {"demo": True, "done": True})[1]
    assert s["first_run"] is False and s["demo"] is True
    assert call(base, "GET", "/health")[1]["keys"]["mode"] == "demo"
    assert UserConfig(c.cfg.dir).get("setup_done") is True
    html = raw(base, "/welcome?lang=fr")
    assert "wiz.keyTitle" in html and 'data-page="welcome"' in html and "Bienvenue" in html


def test_restart_and_quit_buttons(app):
    base, h, c = app()
    assert post(base, "/app/restart")[0] == 409                    # no launcher behind this harness
    calls = []
    c.stop_cb = calls.append
    assert post(base, "/app/restart")[1] == {"ok": True, "restart": True}
    wait_for(lambda: calls == [True])
    assert post(base, "/app/quit")[0] == 202
    wait_for(lambda: calls == [True, False])
    assert '"app_restart"' in (c.cfg.dir / "audit.jsonl").read_text()


def test_new_remote_token(app, tmp_path):
    base, h, c = app(token="o" * 32, remote_mode=True)
    r = post(base, "/app/remote/token")[1]
    assert len(r["token"]) >= 24 and r["active"] and c.auth.check_token(r["token"]) and not c.auth.check_token("o" * 32)
    assert (c.cfg.dir / "remote-token").read_text().strip() == r["token"]
    assert r["token"] not in (c.cfg.dir / "audit.jsonl").read_text()


def test_cli_serve_restart_loop(monkeypatch):
    codes = iter([RESTART_CODE, 0])
    seen = []
    monkeypatch.setattr(cli, "serve", lambda args: seen.append(args.port) or next(codes))
    assert cli.main(["serve", "--port", "8123"]) == 0 and seen == [8123, 8123]


def test_settings_page_vs_settings_json(app):
    base, h, c = app()
    req = urllib.request.Request(base + "/settings", headers={"Accept": "text/html,application/xhtml+xml"})
    html = urllib.request.urlopen(req).read().decode()
    assert 'data-page="settings"' in html and "set.sec.keys" in html and "X-CSRF-Token" in html
    assert "idc" in call(base, "GET", "/settings")[1]               # the JSON API keeps working


# ------------------------------------------------------------------------- navigation
@pytest.mark.parametrize("name,page", [("chat", CHAT_PAGE), ("dashboard", PAGE), ("settings", SETTINGS_PAGE),
                                        ("connect", CONNECT_PAGE)])
def test_navigation_on_every_page(name, page):
    assert f'data-page="{name}"' in page
    for href in ('href="/"', 'href="/dashboard"', 'href="/settings"', 'href="/connect"'):
        assert href in page, href
    assert 'aria-current' in page
    if name != "chat":
        assert 'class="back" href="/"' in page          # always a way back to the chat


def test_chat_history_and_drawer_nav():
    assert "history.pushState" in CHAT_PAGE and 'addEventListener("popstate"' in CHAT_PAGE
    assert CHAT_PAGE.count('class="tabs"') == 2          # header (desktop) + drawer (mobile)
    assert 'sessionStorage.getItem("chatCur")' in CHAT_PAGE


# ------------------------------------------------------------------------- collapsible work trace
def test_trace_block_markup():
    for s in ("trace.title", "trace.pending", "localStorage.getItem(\"traceOpen\")", "aria-expanded", "aria-controls",
              "▸", "▾"):
        assert s in CHAT_PAGE, s
    assert 'id="popups"' in CHAT_PAGE and "#popups" in CHAT_PAGE   # approval cards live outside the log


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_trace_routing_and_summary_in_node():
    js = CHAT_PAGE
    grab = lambda name: re.search(r"function " + name + r"\(.*?\n}\n", js, re.S).group(0)
    src = "\n".join([
        "const I18N={en:{'trace.agents':'{n} agents','trace.agent1':'1 agent','trace.actions':'{n} actions','trace.action1':'1 action'}};",
        "const LANG='en'; function t(k,v){ let s=I18N.en[k]||k; return v?s.replace(/\\{(\\w+)\\}/g,(m,n)=>String(v[n])):s; }",
        "function depth(id){ return id ? id.split('.').length-1 : 0; }",
        grab("traceKind"), grab("traceSummary"), grab("traceCount"),
        """
        const evs=[{kind:'user'},{kind:'status',status:'running'},{kind:'audit',event:'spawn',child:'root.1'},
          {kind:'audit',event:'spawn',child:'root.2'},{kind:'audit',tool:'read_file'},{kind:'audit',tool:'list_files'},
          {kind:'approval',approval:'a1',status:'pending'},{kind:'approval',approval:'a2',status:'pending'},
          {kind:'approval',approval:'a1',status:'approved'},{kind:'message',agent:'root.1',final:true,content:'x'},
          {kind:'message',agent:'root',final:false,content:'plan'},{kind:'message',agent:'root',final:true,content:'answer'},
          {kind:'status',status:'done'}];
        const st={agents:0,actions:0,pending:new Set()}; const kinds=evs.map(traceKind); evs.forEach(e=>traceCount(st,e));
        console.log(JSON.stringify({kinds, sum:traceSummary(st), pending:[...st.pending]}));
        """])
    out = json.loads(subprocess.run(["node", "-e", src], capture_output=True, text=True, check=True).stdout)
    assert out["kinds"] == ["turn", "out", "trace", "trace", "trace", "trace", "trace", "trace", "trace", "trace",
                            "trace", "out", "out"]           # final answer + end-of-turn line stay outside
    assert out["sum"] == "2 agents · 2 actions" and out["pending"] == ["a2"]


# ------------------------------------------------------------------------- desktop
def test_desktop_windowed_streams_and_single_instance(tmp_path, monkeypatch, app):
    from agent import desktop
    monkeypatch.setattr("sys.stderr", None)
    monkeypatch.setattr("sys.stdout", None)
    log = desktop.ensure_streams(tmp_path / "data" / "app.log")
    import sys
    print("hello log", file=sys.stderr)
    sys.stderr.flush()
    monkeypatch.undo()
    assert log and "hello log" in (tmp_path / "data" / "app.log").read_text()
    base, h, c = app()
    port = int(base.rsplit(":", 1)[1])
    monkeypatch.delenv("AGENT_PORT", raising=False)
    assert desktop.running_instance(port) == f"http://127.0.0.1:{port}/"
    assert desktop.running_instance(1) is None
