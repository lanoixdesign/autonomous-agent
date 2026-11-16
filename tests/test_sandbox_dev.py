"""v0.8: sandbox mode ("Bac à sable": allowlist, work folder only, no network, no keys, limits; always on in
Simple mode, Expert can turn it off) and developer mode (templates, Coder/Tester rules, sandboxed preview,
tests in the sandbox, .zip download)."""
import io
import json
import os
import sys
import time
import urllib.request
import zipfile

import pytest

from agent import devmode, sandbox
from agent.audit import AuditLog
from agent.keys import role_task
from agent.llm import MockLLM
from agent.loop import Agent, Budget
from agent.permissions import Permissions
from agent.tools import default_registry
from test_harness import call, finished, wait_for
from test_settings_ui import app, csrf, post, raw  # noqa: F401  (fixtures / helpers)

POSIX = os.name == "posix"


def run(ws, cmd, **kw):
    return sandbox.run(ws, cmd, **kw)


# ------------------------------------------------------------------------- command parsing / allowlist
@pytest.mark.parametrize("cmd", ["ls; rm -rf /", "cat a | sh", "echo x > f", "echo $HOME", "echo `id`", "ls && pwd",
                                 "cat <f", "ls\nrm f", "python -c 'print(1)'", "(ls)", "ls & pwd"])
def test_shell_operators_are_refused(ws, cmd):
    with pytest.raises(sandbox.SandboxError):
        run(ws, cmd)


@pytest.mark.parametrize("cmd", ["curl http://example.com", "wget x", "bash -c ls", "sh x.sh", "sudo ls", "rm2 x",
                                 "/bin/ls", "./tool", "nc -l 80", "ssh host", "git push", "pip install x", "node x.js"])
def test_commands_outside_the_allowlist_are_refused(ws, cmd):
    with pytest.raises(sandbox.SandboxError) as e:
        run(ws, cmd)
    assert "not allowed" in str(e.value)


def test_builtin_commands_work_inside_the_work_folder(ws):
    assert run(ws, "ls").startswith("exit=0") and "hello.txt" in run(ws, "ls")
    assert ".env" not in run(ws, "ls") and ".env" in run(ws, "ls -a")
    assert "hello world" in run(ws, "cat hello.txt")
    assert run(ws, "head -n 1 hello.txt").splitlines()[1] == "hello world"
    assert run(ws, "tail -n 1 hello.txt").splitlines()[1] == "second line"
    assert "2 hello.txt" in run(ws, "wc -l hello.txt")
    assert "hello.txt:1:hello world" in run(ws, "grep -rn hello .")
    assert run(ws, "grep nothing hello.txt").startswith("exit=1")
    assert run(ws, "mkdir -p a/b").startswith("exit=0") and (ws / "a" / "b").is_dir()
    run(ws, "cp hello.txt a/b/copy.txt")
    assert (ws / "a" / "b" / "copy.txt").read_text().startswith("hello")
    assert "./a/b/copy.txt" in run(ws, "find . -name '*.txt'")
    run(ws, "mv a/b/copy.txt a/moved.txt")
    assert (ws / "a" / "moved.txt").exists()
    run(ws, "rm -r a")
    assert not (ws / "a").exists()
    assert run(ws, "echo hi there") == "exit=0\nhi there"
    with pytest.raises(sandbox.SandboxError):
        run(ws, "find . -exec rm {} +")
    with pytest.raises(sandbox.SandboxError):
        run(ws, "find . -delete")
    with pytest.raises(sandbox.SandboxError):
        run(ws, "rm -rf .")


@pytest.mark.parametrize("cmd", ["cat /etc/passwd", "cat ../outside.txt", "ls ..", "cat ~/.ssh/id_rsa", "ls /",
                                 "cp hello.txt ../stolen.txt", "rm ../outside.txt", "grep -r root /etc",
                                 "find / -name passwd", "mkdir ../evil", "python ../outside.py"])
def test_paths_outside_the_work_folder_are_refused(ws, cmd):
    (ws.parent / "outside.txt").write_text("private")
    (ws.parent / "outside.py").write_text("print('x')")
    with pytest.raises(sandbox.SandboxError) as e:
        run(ws, cmd)
    assert "not allowed" in str(e.value)
    assert (ws.parent / "outside.txt").read_text() == "private"


@pytest.mark.skipif(not POSIX, reason="symlinks need privileges on Windows")
def test_symlinks_pointing_outside_are_refused(ws, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET")
    (ws / "link.txt").symlink_to(secret)
    (ws / "dirlink").symlink_to(tmp_path)
    for cmd in ("cat link.txt", "cat dirlink/secret.txt", "cp link.txt copy.txt", "grep -r SECRET dirlink"):
        with pytest.raises(sandbox.SandboxError) as e:
            run(ws, cmd)
        assert "outside" in str(e.value)
    assert "TOP SECRET" not in run(ws, "grep -r SECRET .")       # walking does not follow links out
    run(ws, "rm link.txt")                                      # removing the link itself is fine
    assert secret.exists() and not os.path.lexists(ws / "link.txt")


def test_private_app_data_is_refused_even_inside_the_work_folder(ws):
    state = ws / ".agent"
    state.mkdir()
    (state / "secrets.json").write_text('{"k": "sk-SECRET"}')
    with pytest.raises(sandbox.SandboxError):
        run(ws, "cat .agent/secrets.json", deny=[state])
    assert "sk-SECRET" not in run(ws, "grep -r sk- .", deny=[state])


# ------------------------------------------------------------------------- python in the sandbox
def py(ws, name, code, **kw):
    (ws / name).write_text(code)
    return run(ws, f"python {name}", **kw)


def test_python_runs_with_a_minimal_env_without_keys(ws, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-leak-0123456789")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_should_never_leak_0123456789abcd")
    out = py(ws, "env.py", "import os, json; print(json.dumps(dict(os.environ)))")
    assert out.startswith("exit=0")
    env = json.loads(out.split("\n", 1)[1])
    assert "OPENAI_API_KEY" not in env and "GITHUB_TOKEN" not in env
    assert "should-never-leak" not in out and "should_never_leak" not in out
    assert os.path.realpath(env["HOME"]) == os.path.realpath(ws)


def test_python_network_is_blocked(ws):
    out = py(ws, "net.py", "import socket\ntry:\n socket.create_connection(('127.0.0.1', 9), timeout=1)\n print('CONNECTED')\n"
                           "except PermissionError as e:\n print('blocked', e)\n"
                           "import urllib.request\ntry:\n urllib.request.urlopen('http://example.com', timeout=2)\n"
                           " print('FETCHED')\nexcept Exception as e:\n print('blocked2', e)\n")
    assert "blocked" in out and "blocked2" in out and "CONNECTED" not in out and "FETCHED" not in out


def test_python_cannot_touch_files_outside(ws, tmp_path):
    (tmp_path / "private.txt").write_text("PRIVATE")
    out = py(ws, "files.py", f"""
for what, fn in (("read", lambda: open({str(tmp_path / 'private.txt')!r}).read()),
                 ("write", lambda: open({str(tmp_path / 'evil.txt')!r}, "w").write("x")),
                 ("list", lambda: __import__("os").listdir({str(tmp_path)!r})),
                 ("remove", lambda: __import__("os").remove({str(tmp_path / 'private.txt')!r}))):
    try:
        fn(); print(what, "DONE")
    except PermissionError as e:
        print(what, "blocked")
open("inside.txt", "w").write("ok"); print("inside ok")
""")
    assert out.count("blocked") == 4 and "DONE" not in out and "inside ok" in out
    assert (tmp_path / "private.txt").read_text() == "PRIVATE" and not (tmp_path / "evil.txt").exists()
    assert (ws / "inside.txt").read_text() == "ok"


def test_python_cannot_start_programs_or_load_native_code(ws):
    out = py(ws, "proc.py", """
import subprocess, os
for what, fn in (("popen", lambda: subprocess.run(["ls"])), ("system", lambda: os.system("ls")),
                 ("ctypes", lambda: __import__("ctypes"))):
    try:
        fn(); print(what, "DONE")
    except (PermissionError, ImportError) as e:
        print(what, "blocked")
""")
    assert out.count("blocked") == 3 and "DONE" not in out


def test_python_time_and_output_limits(ws):
    t0 = time.monotonic()
    with pytest.raises(sandbox.SandboxError) as e:
        py(ws, "loop.py", "while True:\n    pass\n", timeout=2)
    assert "time limit" in str(e.value) and time.monotonic() - t0 < 10
    out = py(ws, "big.py", "print('x' * 50000)", max_output=1000)
    assert "chars truncated" in out and len(out) < 1200


def test_python_module_allowlist_and_pytest(ws):
    with pytest.raises(sandbox.SandboxError):
        run(ws, "python -m http.server")
    with pytest.raises(sandbox.SandboxError):
        run(ws, "python -m pip install requests")
    (ws / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (ws / "test_calc.py").write_text("import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n"
                                     "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n")
    out = run(ws, "python -m unittest -v")
    assert out.startswith("exit=0") and "OK" in out
    out = run(ws, "pytest -q -p no:cacheprovider")
    assert out.startswith("exit=0") and "1 passed" in out


# ------------------------------------------------------------------------- shell tool + settings
def test_shell_tool_uses_the_sandbox_when_on(ctx, ws):
    reg = default_registry(enable_web=False, enable_github=False)
    tool = reg.get("shell")
    ctx.sandbox = lambda: True
    assert "hello.txt" in tool.func(ctx, {"command": "ls"})
    from agent.tools import ToolError
    with pytest.raises(ToolError) as e:
        tool.func(ctx, {"command": "cat /etc/passwd"})
    assert "outside" in str(e.value)
    with pytest.raises(ToolError):
        tool.func(ctx, {"command": "ls | wc -l"})
    ctx.sandbox = lambda: False
    if POSIX:
        assert tool.func(ctx, {"command": "echo a | tr a b"}).endswith("b")    # real shell when off


def test_agent_system_prompt_mentions_the_sandbox(ctx, tmp_path):
    ctx.sandbox = lambda: True
    a = Agent(MockLLM([{"content": "ok"}]), default_registry(enable_web=False, enable_github=False), Permissions(),
              AuditLog(tmp_path / "a.jsonl"), ctx, Budget())
    assert "Sandbox is on" in a.messages[0]["content"]
    ctx.sandbox = lambda: False
    a.refresh_system()
    assert "Sandbox is on" not in a.messages[0]["content"]
    ctx.sandbox = lambda: 1 / 0          # a broken setting means: stay safe
    assert ctx.sandbox_on() is True


def test_sandbox_setting_forced_in_simple_mode_and_expert_can_turn_it_off(app, tmp_path):
    base, h, control = app()
    st, v = call(base, "GET", "/app/settings")
    assert v["sandbox"] == {"saved": True, "effective": True, "forced": True}
    st, v = post(base, "/app/settings", {"sandbox": False})
    assert st == 200 and v["sandbox"]["effective"] is True          # Simple mode: still on
    assert control.sandbox_on() is True and call(base, "GET", "/config")[1]["sandbox"] is True
    st, v = post(base, "/app/settings", {"ui_mode": "expert"})
    assert v["sandbox"] == {"saved": False, "effective": False, "forced": False}
    assert control.sandbox_on() is False and call(base, "GET", "/config")[1]["sandbox"] is False
    st, v = post(base, "/app/settings", {"sandbox": True})
    assert v["sandbox"]["effective"] is True
    st, v = post(base, "/app/settings", {"sandbox": "no"})
    assert st == 400 and v["code"] == "bad_bool"
    audit = (tmp_path / "state" / "audit.jsonl").read_text()
    assert '"sandbox_off"' in audit and '"sandbox_on"' in audit


def test_sandbox_setting_needs_csrf(app):
    base, h, control = app()
    st, _ = call(base, "POST", "/app/settings", {"sandbox": False})
    assert st == 403


def test_cli_sandbox_flag(tmp_path, monkeypatch):
    import argparse
    from agent import cli
    monkeypatch.setattr(cli, "make_router", lambda *a: None)
    monkeypatch.delenv("AGENT_SANDBOX", raising=False)
    base = dict(workspace=str(tmp_path / "w"), state_dir=str(tmp_path / "s"), permissions=None, yolo=False)
    perms, ctx, state = cli.parts(argparse.Namespace(**base, sandbox=True))
    assert ctx.sandbox_on() and state in ctx.deny_paths
    perms, ctx, state = cli.parts(argparse.Namespace(**base, sandbox=False))
    assert not ctx.sandbox_on()
    monkeypatch.setenv("AGENT_SANDBOX", "1")
    perms, ctx, state = cli.parts(argparse.Namespace(**base, sandbox=False))
    assert ctx.sandbox_on()


# ------------------------------------------------------------------------- developer mode
def test_role_mapping_for_coder_and_tester():
    for r in ("Coder: write index.html", "Codeur : écrire le site", "Tester: run the tests", "Testeur : vérifier"):
        assert role_task(r) == "code"


def test_templates_create_list_and_never_overwrite(tmp_path):
    p = devmode.Projects(tmp_path)
    web = p.create("Ma Boulangerie", "web", "fr")
    assert web["name"] == "ma-boulangerie" and web["kind"] == "web" and web["preview"].startswith("/preview/")
    assert "Bonjour" in (tmp_path / "projects" / "ma-boulangerie" / "index.html").read_text()
    pyp = p.create("Calc", "python", "en")
    assert sorted(pyp["list"]) == ["README.md", "main.py", "test_main.py"] and pyp["preview"] is None
    with pytest.raises(devmode.DevError) as e:
        p.create("calc", "web")
    assert e.value.code == "exists"
    for bad in ("", "  ", "!!!"):
        with pytest.raises(devmode.DevError):
            p.create(bad, "web")
    with pytest.raises(devmode.DevError):
        p.create("x", "rust")
    assert {x["name"] for x in p.list()} == {"ma-boulangerie", "calc"}
    with pytest.raises(devmode.DevError):
        p.path("../etc")


def test_project_tests_run_in_the_sandbox(tmp_path):
    p = devmode.Projects(tmp_path)
    p.create("calc", "python")
    r = p.test("calc")
    assert r["ok"] and r["summary"]["passed"] == 1 and r["summary"]["failed"] == 0
    (tmp_path / "projects" / "calc" / "main.py").write_text("def greet(n):\n    return 'nope'\n")
    r = p.test("calc")
    assert not r["ok"] and r["summary"]["failed"] == 1
    devmode._PYTEST = False                   # stdlib unittest fallback (desktop builds without pytest)
    try:
        r = p.test("calc")
        assert not r["ok"] and r["runner"] == "unittest" and r["summary"]["failed"] == 1
    finally:
        devmode._PYTEST = None
    # a test that tries to escape is stopped by the sandbox
    (tmp_path / "projects" / "calc" / "test_main.py").write_text(
        "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n"
        "        open('/tmp/' + 'escape.txt', 'w').write('x')\n")
    r = p.test("calc")
    assert not r["ok"] and "outside the work folder" in r["output"]


def test_website_check_finds_missing_files(tmp_path):
    p = devmode.Projects(tmp_path)
    p.create("site", "web")
    assert p.test("site")["ok"]
    idx = tmp_path / "projects" / "site" / "index.html"
    idx.write_text(idx.read_text().replace("style.css", "missing.css") + '<img src="https://cdn.example.com/x.png">')
    r = p.test("site")
    assert not r["ok"] and any("missing.css" in x for x in r["problems"]) and any("internet" in x for x in r["problems"])


def test_zip_contains_only_the_project(tmp_path):
    p = devmode.Projects(tmp_path)
    p.create("calc", "python")
    d = tmp_path / "projects" / "calc"
    (d / "__pycache__").mkdir()
    (d / "__pycache__" / "x.pyc").write_bytes(b"x")
    (d / ".secret").write_text("x")
    body, name = p.zip("calc")
    names = zipfile.ZipFile(io.BytesIO(body)).namelist()
    assert name == "calc.zip" and sorted(names) == ["calc/README.md", "calc/main.py", "calc/test_main.py"]


def test_preview_files_are_confined(tmp_path):
    p = devmode.Projects(tmp_path)
    p.create("site", "web")
    (tmp_path / "secret.txt").write_text("S")
    tok = p.token("site")
    body, ctype = p.preview_file(tok, "site", "")
    assert b"<!doctype html>" in body and ctype.startswith("text/html")
    assert p.preview_file(tok, "site", "style.css")[1].startswith("text/css")
    for bad in ("../../secret.txt", "%2e%2e/%2e%2e/secret.txt", ".hidden", "/etc/passwd"):
        with pytest.raises(devmode.DevError):
            p.preview_file(tok, "site", bad)
    with pytest.raises(devmode.DevError):
        p.preview_file("0" * 24, "site", "")
    if POSIX:
        (tmp_path / "projects" / "site" / "leak.txt").symlink_to(tmp_path / "secret.txt")
        with pytest.raises(devmode.DevError):
            p.preview_file(tok, "site", "leak.txt")


def test_dev_rules_name_coder_and_tester():
    r = devmode.rules("site", "web")
    assert "Coder:" in r and "Tester:" in r and "projects/site/" in r


# ------------------------------------------------------------------------- developer mode over HTTP
def get_raw(base, path, headers=None):
    req = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_dev_http_create_preview_test_zip(app, ctx):
    base, h, control = app()
    assert "data-page=\"dev\"" in raw(base, "/dev") and 'href="/dev"' in raw(base, "/")
    st, d = call(base, "GET", "/dev/projects")
    assert st == 200 and d["available"] and d["projects"] == [] and d["sandbox"] is True
    st, p = call(base, "POST", "/dev/projects", {"name": "Hello Site", "kind": "web", "lang": "en"})
    assert st == 201 and p["name"] == "hello-site"
    st, e = call(base, "POST", "/dev/projects", {"name": "hello site", "kind": "web"})
    assert st == 409 and e["code"] == "exists"
    st, hd, body = get_raw(base, p["preview"])
    assert st == 200 and b"<!doctype html>" in body
    csp = hd["Content-Security-Policy"]
    assert csp.startswith("sandbox allow-scripts") and "connect-src 'none'" in csp and "allow-same-origin" not in csp
    st, hd, body = get_raw(base, p["preview"].rstrip("/"))
    assert st in (200, 301)
    assert get_raw(base, p["preview"] + "..%2f..%2fhello.txt")[0] == 404
    assert get_raw(base, "/preview/" + "0" * 24 + "/hello-site/")[0] == 404
    st, r = call(base, "POST", "/dev/test", {"project": "hello-site"})
    assert st == 200 and r["ok"] and r["runner"] == "links"
    st, r = call(base, "POST", "/dev/test", {"project": "nope"})
    assert st == 404
    st, hd, body = get_raw(base, "/dev/zip?project=hello-site")
    assert st == 200 and hd["Content-Type"] == "application/zip" and "hello-site.zip" in hd["Content-Disposition"]
    assert "hello-site/index.html" in zipfile.ZipFile(io.BytesIO(body)).namelist()
    audit = (ctx.workspace.parent / "state" / "audit.jsonl").read_text()
    assert '"dev_create"' in audit and '"dev_test"' in audit and '"dev_zip"' in audit


def test_dev_http_refuses_cross_origin_and_needs_token(app):
    base, h, control = app(token="tok-123456789")
    st, _ = call(base, "GET", "/dev/projects")
    assert st == 401
    st, _ = call(base, "POST", "/dev/projects", {"name": "x", "kind": "web"},
                 headers={"Authorization": "Bearer tok-123456789", "Origin": "http://evil.example"})
    assert st == 403
    st, p = call(base, "POST", "/dev/projects", {"name": "x", "kind": "web"},
                 headers={"Authorization": "Bearer tok-123456789"})
    assert st == 201
    assert get_raw(base, p["preview"])[0] == 200          # the signed preview URL works without the token


def test_dev_conversation_gets_coder_tester_rules(app, ctx):
    base, h, control = app()
    call(base, "POST", "/dev/projects", {"name": "calc", "kind": "python"})
    st, e = call(base, "POST", "/tasks", {"task": "build", "dev": "missing"})
    assert st == 404
    st, task = call(base, "POST", "/tasks", {"task": "Make a calculator", "dev": "calc"})
    assert st == 201 and task["dev"] == "calc"
    finished(base, task["id"])
    t = h.get(task["id"])
    sysmsg = t.agent.messages[0]["content"]
    assert "DEVELOPER MODE" in sysmsg and "projects/calc/" in sysmsg and "Coder:" in sysmsg and "Tester:" in sysmsg
    st, plain = call(base, "POST", "/tasks", {"task": "hello"})
    finished(base, plain["id"])
    assert "DEVELOPER MODE" not in h.get(plain["id"]).agent.messages[0]["content"]
