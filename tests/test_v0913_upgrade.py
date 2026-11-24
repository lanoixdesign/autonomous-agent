"""v0.9.13: a new version starts even when an old one still runs, after a crash, or with old/damaged files."""
import json
import os
import socket
import sqlite3
import threading

import pytest

from agent import __version__, desktop, harness, i18n, instance, remote
from agent.harness import Harness, make_server
from agent.llm import MockLLM, SwitchLLM
from agent.loop import Agent, Budget
from agent.permissions import Permissions
from agent.store import Store
from agent.tools import default_registry
from agent.userconfig import AppControl, SecretStore, UserConfig



@pytest.fixture
def server(ctx, tmp_path):  # noqa: F811
    """A real harness on a free port, whose Quit button really stops it (like the desktop app)."""
    started = []

    def start(name="old"):
        state = tmp_path / name
        cfg = UserConfig(state)
        control = AppControl(cfg, SecretStore(state / "secrets.json", use_keyring=False), perms=Permissions(),
                             home=str(state))

        def factory(task, audit, confirm, cancel, on_event):
            return Agent(SwitchLLM(control, "text", MockLLM), default_registry(enable_web=False, enable_github=False),
                         Permissions(), audit, ctx, Budget(), confirm=confirm, on_event=on_event, cancel=cancel)
        store = Store(state / "harness.sqlite3")
        h = Harness(factory, state / "audit.jsonl", approval_timeout=5, workspace=ctx.workspace, store=store,
                    scheduler_tick=None)
        control.h, control.auth, h.control = h, remote.Auth(None), control
        control.boot = {"workspace": str(ctx.workspace), "max_tasks": h.max_tasks,
                        "remote": {"enabled": False, "tunnel": "none", "public_url": ""}}
        srv = make_server(h, "127.0.0.1", 0, None, warn=lambda m: None)
        control.stop_cb = lambda restart: (srv.shutdown(), srv.server_close())
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append((srv, h, store))
        return srv.server_address[1], h, control
    yield start
    for srv, h, store in started:
        h.shutdown()
        try:
            srv.shutdown()
            srv.server_close()
        except OSError:
            pass
        store.close()


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------ old copy still running
def test_old_version_running_is_asked_to_quit_and_the_port_is_freed(server, tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "__version__", "0.9.12")          # the copy running is the previous version
    port, h, c = server()
    data = tmp_path / "newdata"
    info = instance.find(data, [port])
    assert info and info["version"] == "0.9.12" and "record" not in info
    logs = []
    assert instance.stop(info, logs.append, wait=8) is True       # via the Quit button API (old versions have it)
    assert instance.probe(port) is None and any("quit: True" in m for m in logs)


def test_same_version_running_just_opens_it(server, tmp_path, monkeypatch):
    port, h, c = server()
    monkeypatch.setattr(desktop, "PREFERRED_PORT", port)
    monkeypatch.delenv("AGENT_PORT", raising=False)
    url, taken = desktop._take_over({"data": tmp_path / "d"}, lambda k, **kw: k)
    assert url == f"http://127.0.0.1:{port}/" and taken is False
    assert instance.probe(port) is not None                       # not stopped


def test_takeover_endpoint_needs_the_stop_token(server, tmp_path, monkeypatch):
    port, h, c = server()
    monkeypatch.setenv(instance.TOKEN_ENV, "right-token-123456")
    bad = {"url": f"http://127.0.0.1:{port}/", "port": port, "record": {"token": "wrong"}}
    assert instance._post(bad["url"] + "app/takeover", {instance.TOKEN_HEADER: "wrong"}, 3) == 403
    assert instance.probe(port) is not None
    rec = {"pid": os.getpid(), "port": port, "version": "0.9.13", "token": "right-token-123456"}
    good = {"url": f"http://127.0.0.1:{port}/", "port": port, "version": "x", "record": rec}
    assert instance._post(good["url"] + "app/takeover", {instance.TOKEN_HEADER: rec["token"]}, 3) == 202
    assert instance.wait_gone(port, 8)


def test_port_busy_with_something_else_uses_another_port(monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        busy = s.getsockname()[1]
        monkeypatch.setattr(desktop, "PREFERRED_PORT", busy)
        monkeypatch.delenv("AGENT_PORT", raising=False)
        assert instance.probe(busy, timeout=0.5) is None            # not an autonomous-agent
        p = desktop.free_port()
        assert p != busy and p > 0


# ------------------------------------------------------------------ crash leftovers
def test_stale_instance_file_is_removed(tmp_path):
    port = _free_port()
    instance.write(tmp_path, port, "0.9.12", "tok")
    rec = json.loads((tmp_path / "instance.json").read_text())
    rec["pid"] = 999999999                                         # the process is gone (crash)
    (tmp_path / "instance.json").write_text(json.dumps(rec))
    logs = []
    assert instance.find(tmp_path, [port], logs.append) is None
    assert not (tmp_path / "instance.json").exists() and "stale" in logs[0]
    assert instance.pid_alive(os.getpid()) and not instance.pid_alive(999999999)


def test_instance_file_written_private_and_removed_only_by_its_owner(tmp_path):
    instance.write(tmp_path, 8765, __version__, "tok")
    if os.name == "posix":
        assert (tmp_path / "instance.json").stat().st_mode & 0o077 == 0
    instance.remove(tmp_path, only_pid=os.getpid() + 1)
    assert (tmp_path / "instance.json").exists()
    instance.remove(tmp_path, only_pid=os.getpid())
    assert not (tmp_path / "instance.json").exists()


# ------------------------------------------------------------------ old or damaged files
def test_old_format_settings_are_tolerated(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps(
        {"version": 1, "lang": 5, "remote": "yes", "ui_mode": 3, "sandbox": "on", "setup_done": True,
         "unknown_future_key": {"a": 1}}))
    cfg = UserConfig(tmp_path)
    assert cfg.get("lang") is None and cfg.get("ui_mode") == "simple" and cfg.get("sandbox") is True
    assert cfg.get("remote")["enabled"] is False and cfg.get("setup_done") is True
    (tmp_path / "providers-ui.json").write_text(json.dumps({"providers": [{"id": "p1", "provider": "ollama"}, "x"]}))
    assert [p["id"] for p in UserConfig(tmp_path).providers] == ["p1"]


def test_damaged_settings_and_secrets_are_kept_aside(tmp_path):
    (tmp_path / "settings.json").write_text("{not json")
    cfg = UserConfig(tmp_path)
    assert cfg.get("ui_mode") == "simple"
    assert any(p.name.startswith("settings.json.broken-") for p in tmp_path.iterdir())
    (tmp_path / "secrets.json").write_text(json.dumps({"secrets": ["not", "a", "dict"]}))
    assert SecretStore(tmp_path / "secrets.json", use_keyring=False).get("x") is None


def test_damaged_database_is_kept_aside_and_a_new_one_created(tmp_path):
    db = tmp_path / "harness.sqlite3"
    db.write_bytes(b"this is not a database" * 100)
    st = Store(db)
    assert st.backup is not None and st.backup.exists()
    st.put("tasks", "t1", {"id": "t1", "task": "hi"})
    assert st.all("tasks")[0]["id"] == "t1"
    st.close()


def test_old_conversation_rows_do_not_stop_the_start(tmp_path, ctx):  # noqa: F811
    db = tmp_path / "harness.sqlite3"
    st = Store(db)
    st.put("tasks", "good", {"id": "good", "task": "hello", "status": "done"})
    st.put("tasks", "old", {"id": "old", "task": "x", "status": "done", "total": "not-a-dict"})
    st._db.execute("INSERT INTO tasks (id, data) VALUES ('broken', '{oops')")
    st._db.execute("INSERT INTO rules (id, data) VALUES ('r', '[1,2]')")
    h = Harness(lambda *a: None, tmp_path / "audit.jsonl", store=st, scheduler_tick=None)
    assert h.get("good") is not None and h.get("old") is None and h.get("broken") is None
    h.shutdown()
    st.close()
    assert sqlite3.connect(db).execute("SELECT count(*) FROM tasks").fetchone()[0] == 3   # nothing deleted


# ------------------------------------------------------------------ never a silent failure
def test_start_error_writes_the_log_and_opens_a_plain_page(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path))
    monkeypatch.setenv("AGENT_NO_BROWSER", "1")
    monkeypatch.setenv("AGENT_LANG", "fr")
    monkeypatch.setenv("AGENT_LOG_FILE", "1")
    import sys
    out, err = sys.stdout, sys.stderr

    def boom(*a):
        raise RuntimeError("panne au démarrage gsk_ABCDEFGHIJKLMNOP")
    monkeypatch.setattr(desktop, "_main", boom)
    try:
        assert desktop.main([]) == 1
    finally:
        sys.stdout, sys.stderr = out, err
    page = (tmp_path / "data" / "start-error.html").read_text(encoding="utf-8")
    assert "L&#x27;appli n&#x27;a pas pu démarrer" in page and "panne au démarrage" in page
    assert "gsk_ABCD" not in page and "gsk_••••" in page                 # keys never shown
    assert str(tmp_path / "data" / "app.log") in page
    assert "RuntimeError" in (tmp_path / "data" / "app.log").read_text(encoding="utf-8")


def test_strings_exist_in_both_languages():
    for k in ("desktop.replacing", "desktop.sameVersion", "desktop.otherPort", "desktop.translocated",
              "desktop.err.title", "desktop.err.s3", "desktop.err.s4"):
        assert i18n.EN.get(k) and i18n.FR.get(k), k
