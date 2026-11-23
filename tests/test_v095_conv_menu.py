"""v0.9.5: per-conversation menu (pin, open the folder, delete) + its security (CSRF, local only, traversal)."""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agent import i18n
from agent.harness import CHAT_PAGE, ConvError, Harness, make_server, render_page
from agent.llm import MockLLM
from agent.loop import Agent, Budget
from agent.permissions import Permissions
from agent.store import Store
from agent.swarm import SwarmConfig
from agent.tools import default_registry

TERMINAL = ("done", "stopped", "cancelled", "error")
needs_symlinks = pytest.mark.skipif(os.name == "nt", reason="symbolic links need extra rights on Windows")


def wait_for(fn, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


@pytest.fixture
def env(ctx, tmp_path):
    """start() -> (base, harness, opened) with a SQLite store and a fake file manager."""
    started = []

    def start(store_path=None):
        def factory(task, audit, confirm, cancel, on_event):
            return Agent(MockLLM([{"content": "ok"}]), default_registry(enable_web=False, enable_github=False),
                         Permissions(), audit, ctx, Budget(), confirm=confirm, on_event=on_event,
                         swarm=SwarmConfig(), cancel=cancel)
        store = Store(store_path or tmp_path / "state" / "h.sqlite3")
        h = Harness(factory, tmp_path / "state" / "audit.jsonl", workspace=ctx.workspace, store=store)
        opened = []
        h.folder_opener = lambda p: opened.append(Path(p)) or True
        srv = make_server(h, "127.0.0.1", 0, None, warn=lambda m: None)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append((srv, h, store))
        return f"http://127.0.0.1:{srv.server_address[1]}", h, opened

    yield start
    for srv, h, store in started:
        h.shutdown()
        srv.shutdown()
        srv.server_close()
        store.close()


def call(base, method, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def csrf(base):
    st, j = call(base, "GET", "/conv/csrf")
    assert st == 200 and len(j["csrf"]) >= 32
    return {"X-CSRF-Token": j["csrf"]}


def new_conv(base, text="hello"):
    st, t = call(base, "POST", "/tasks", {"task": text})
    assert st in (200, 201, 202), t
    wait_for(lambda: call(base, "GET", f"/tasks/{t['id']}")[1]["status"] in TERMINAL)
    return t["id"]


# ------------------------------------------------------------------ pin
def test_pin_is_saved_and_survives_a_restart(env, tmp_path):
    db = tmp_path / "state" / "pin.sqlite3"
    base, h, _ = env(db)
    a, b = new_conv(base, "first"), new_conv(base, "second")
    st, j = call(base, "POST", f"/conv/{a}/pin", {"pinned": True}, csrf(base))
    assert st == 200 and j["pinned"] is True
    rows = {x["id"]: x for x in call(base, "GET", "/tasks")[1]["tasks"]}
    assert rows[a]["pinned"] is True and rows[b]["pinned"] is False
    assert rows[a]["folder"] == f"conversations/{a}"
    h.shutdown()
    base2, h2, _ = env(db)                       # a new process reading the same SQLite file
    rows = {x["id"]: x for x in call(base2, "GET", "/tasks")[1]["tasks"]}
    assert rows[a]["pinned"] is True and rows[b]["pinned"] is False
    st, j = call(base2, "POST", f"/conv/{a}/pin", {"pinned": False}, csrf(base2))
    assert st == 200 and j["pinned"] is False


def test_pin_needs_a_real_boolean(env):
    base, _, _ = env()
    a = new_conv(base)
    assert call(base, "POST", f"/conv/{a}/pin", {"pinned": "yes"}, csrf(base))[0] == 400


# ------------------------------------------------------------------ CSRF
@pytest.mark.parametrize("action,body", [("pin", {"pinned": True}), ("folder", {}), ("delete", {})])
@pytest.mark.parametrize("token", [None, "", "0" * 64, "forged"])
def test_every_action_needs_the_csrf_token(env, action, body, token):
    base, h, opened = env()
    a = new_conv(base)
    hdr = {} if token is None else {"X-CSRF-Token": token}
    st, j = call(base, "POST", f"/conv/{a}/{action}", body, hdr)
    assert st == 403 and j["code"] == "csrf"
    assert h.get(a) is not None and h.get(a).pinned is False and opened == []


def test_cross_site_requests_are_refused_even_with_a_token(env):
    base, h, _ = env()
    a = new_conv(base)
    hdr = {**csrf(base), "Origin": "https://evil.example"}
    assert call(base, "POST", f"/conv/{a}/delete", {}, hdr)[0] == 403
    assert h.get(a) is not None


def test_csrf_token_is_not_readable_cross_site(env):
    base, _, _ = env()
    req = urllib.request.Request(base + "/conv/csrf", headers={"Origin": "https://evil.example"})
    with pytest.raises(urllib.error.HTTPError) as e:
        with urllib.request.urlopen(req, timeout=5) as r:      # if it ever answered, no CORS header
            assert "Access-Control-Allow-Origin" not in r.headers
            raise urllib.error.HTTPError(base, 403, "", r.headers, None)
    assert e.value.code == 403


# ------------------------------------------------------------------ open the folder
def test_open_folder_creates_it_inside_the_work_folder(env, ctx):
    base, h, opened = env()
    a = new_conv(base)
    st, j = call(base, "POST", f"/conv/{a}/folder", {}, csrf(base))
    assert st == 200 and j["opened"] is True and j["rel"] == f"conversations/{a}"
    p = Path(j["path"])
    assert p.is_dir() and opened == [p]
    assert Path(ctx.workspace).resolve() in p.parents
    assert call(base, "GET", f"/tasks/{a}")[1]["folder_path"] == str(p)


def test_open_folder_ignores_any_path_sent_by_the_page(env, tmp_path):
    base, h, opened = env()
    a = new_conv(base)
    st, j = call(base, "POST", f"/conv/{a}/folder", {"path": "/etc", "rel": "../../.."}, csrf(base))
    assert st == 200 and opened == [Path(j["path"])] and Path(j["path"]).name == a


def test_open_folder_only_for_this_computer(env):
    base, h, opened = env()
    a = new_conv(base)
    st, j = call(base, "POST", f"/conv/{a}/folder", {}, {**csrf(base), "X-Forwarded-For": "203.0.113.9"})
    assert st == 403 and j["code"] == "local_only" and opened == []


@pytest.mark.parametrize("path", ["/conv/../etc/folder", "/conv/..%2F..%2Fetc/folder", "/conv/ABCDEF/folder",
                                  "/conv/abc/folder", "/conv/" + "a" * 40 + "/folder", "/conv/abcdef12/rm",
                                  "/conv/abcdef12/folder/x"])
def test_traversal_or_odd_ids_are_not_found(env, path):
    base, h, opened = env()
    st, _ = call(base, "POST", path, {}, csrf(base))
    assert st in (400, 404) and opened == []


def test_unknown_conversation_is_404(env):
    base, _, opened = env()
    st, j = call(base, "POST", "/conv/abcdef1234/folder", {}, csrf(base))
    assert st == 404 and j["code"] == "unknown" and opened == []


@needs_symlinks
def test_a_symlinked_folder_is_refused(env, ctx, tmp_path):
    base, h, opened = env()
    a = new_conv(base)
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, Path(ctx.workspace) / "conversations")
    st, j = call(base, "POST", f"/conv/{a}/folder", {}, csrf(base))
    assert st == 400 and j["code"] == "symlink" and opened == []
    assert not any(outside.iterdir())


def test_a_bad_project_name_is_refused(env):
    base, h, _ = env()
    a = new_conv(base)
    t = h.get(a)
    for bad in ("../x", "..", "a/b", ".hidden", "x" * 80):
        t.dev = bad
        with pytest.raises(ConvError) as e:
            h.conv_folder(t, create=True)
        assert e.value.code == "bad_folder"


def test_private_app_data_is_refused(env, ctx):
    base, h, _ = env()
    a = new_conv(base)
    h.deny_paths = [Path(ctx.workspace) / "conversations"]
    st, j = call(base, "POST", f"/conv/{a}/folder", {}, csrf(base))
    assert st == 400 and j["code"] == "private"


# ------------------------------------------------------------------ delete
def test_delete_keeps_the_folder_by_default(env, ctx, tmp_path):
    db = tmp_path / "state" / "del.sqlite3"
    base, h, _ = env(db)
    a, b = new_conv(base, "keep"), new_conv(base, "other")
    call(base, "POST", f"/conv/{a}/folder", {}, csrf(base))
    folder = Path(ctx.workspace) / "conversations" / a
    (folder / "notes.txt").write_text("mine")
    assert h.store.events(a)
    st, j = call(base, "POST", f"/conv/{a}/delete", {}, csrf(base))
    assert st == 200 and j == {"deleted": a, "folder_deleted": []}
    assert (folder / "notes.txt").read_text() == "mine"           # the files stay
    assert [x["id"] for x in call(base, "GET", "/tasks")[1]["tasks"]] == [b]
    assert call(base, "GET", f"/tasks/{a}")[0] == 404
    assert h.store.events(a) == [] and a not in [r["id"] for r in h.store.all("tasks")]
    audit = (tmp_path / "state" / "audit.jsonl").read_text()
    assert "conversation_deleted" in audit


def test_delete_with_the_box_checked_removes_folder_and_uploads(env, ctx):
    base, h, _ = env()
    a, b = new_conv(base), new_conv(base)
    ws = Path(ctx.workspace)
    for x in (a, b):
        (ws / "conversations" / x).mkdir(parents=True)
        (ws / "uploads" / x).mkdir(parents=True)
    st, j = call(base, "POST", f"/conv/{a}/delete", {"delete_folder": True}, csrf(base))
    assert st == 200 and sorted(j["folder_deleted"]) == sorted([f"conversations/{a}", f"uploads/{a}"])
    assert not (ws / "conversations" / a).exists() and not (ws / "uploads" / a).exists()
    assert (ws / "conversations" / b).is_dir() and (ws / "uploads" / b).is_dir()   # nothing else touched
    assert ws.is_dir()


@needs_symlinks
def test_delete_never_follows_a_symlink(env, ctx, tmp_path):
    base, h, _ = env()
    a = new_conv(base)
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "x.txt").write_text("keep")
    (Path(ctx.workspace) / "conversations").mkdir()
    os.symlink(precious, Path(ctx.workspace) / "conversations" / a)
    st, j = call(base, "POST", f"/conv/{a}/delete", {"delete_folder": True}, csrf(base))
    assert st == 400 and j["code"] == "symlink"
    assert (precious / "x.txt").read_text() == "keep" and h.get(a) is not None


def test_delete_flag_must_be_boolean(env):
    base, h, _ = env()
    a = new_conv(base)
    assert call(base, "POST", f"/conv/{a}/delete", {"delete_folder": "yes"}, csrf(base))[0] == 400
    assert h.get(a) is not None


def test_a_running_conversation_cannot_be_deleted(env):
    base, h, _ = env()
    a = new_conv(base)
    h.get(a).status = "running"
    st, j = call(base, "POST", f"/conv/{a}/delete", {}, csrf(base))
    assert st == 409 and j["code"] == "running" and h.get(a) is not None


def test_a_shared_project_folder_is_not_deleted(env, ctx):
    base, h, _ = env()
    a, b = new_conv(base), new_conv(base)
    h.get(a).dev = h.get(b).dev = "shop"
    (Path(ctx.workspace) / "projects" / "shop").mkdir(parents=True)
    st, j = call(base, "POST", f"/conv/{a}/delete", {"delete_folder": True}, csrf(base))
    assert st == 409 and j["code"] == "shared"
    assert (Path(ctx.workspace) / "projects" / "shop").is_dir()
    st, j = call(base, "POST", f"/conv/{a}/delete", {}, csrf(base))      # without the folder: fine
    assert st == 200


def test_delete_removes_rules_of_that_conversation(env):
    base, h, _ = env()
    a, b = new_conv(base), new_conv(base)
    h.rules["r1"] = {"id": "r1", "scope": "task", "task_id": a}
    h.rules["r2"] = {"id": "r2", "scope": "task", "task_id": b}
    h.store.put("rules", "r1", h.rules["r1"])
    assert call(base, "POST", f"/conv/{a}/delete", {}, csrf(base))[0] == 200
    assert "r1" not in h.rules and "r2" in h.rules
    assert [r["id"] for r in h.store.all("rules")] == []


# ------------------------------------------------------------------ page + words
NEW_KEYS = ["conv.menu", "conv.pin", "conv.unpin", "conv.pinned", "conv.recent", "conv.folder", "conv.delete",
            "conv.isPinned", "conv.folderLine", "conv.copy", "conv.copied", "conv.opened", "conv.openLocal",
            "conv.notOpened", "del.title", "del.text", "del.folder", "del.keep", "del.confirm", "del.cancel",
            "del.done"]


def test_words_exist_in_both_languages_and_use_tu():
    for k in NEW_KEYS:
        assert i18n.EN.get(k) and i18n.FR.get(k), k
        assert i18n.EN[k] != i18n.FR[k] or k in ("conv.menu",), k
        assert not re.search(r"\b(vous|votre|vos)\b", i18n.FR[k], re.I), k
    assert i18n.FR["conv.pinned"] == "Épinglées" and i18n.FR["conv.pin"] == "Épingler"
    assert "{name}" in i18n.FR["del.text"] and "{path}" in i18n.FR["del.keep"]


def test_chat_page_has_an_accessible_menu_and_dialog():
    html = render_page(CHAT_PAGE, "fr", "fr", "dark").decode()
    assert 'id="convmenu" role="menu"' in html and html.count('role="menuitem"') == 4
    assert 'role="alertdialog" aria-modal="true" aria-labelledby="delt" aria-describedby="deld"' in html
    assert re.search(r'<input type="checkbox" id="delfolder">', html)          # unchecked by default
    assert 'id="toast" role="status" aria-live="polite"' in html
    assert 'id="foldermsg" aria-live="polite"' in html
    for js in ('setAttribute("aria-haspopup","menu")', 'setAttribute("aria-expanded"', '"X-CSRF-Token"',
               'e.key==="Escape"', 'e.key==="ArrowDown"', 'e.key==="Tab"', '"/conv/csrf"',
               'if(!force && (menuFor || delFor)) return;'):
        assert js in html, js
    assert "@media (hover:none),(max-width:760px){.cmore{opacity:1}}" in html     # always visible on mobile


def test_menu_colors_stay_calm():
    html = render_page(CHAT_PAGE, "fr", "fr", "dark").decode()
    css = html[html.index(".cmore{"):html.index("#toast{")]
    css += html[html.index("#toast{"):html.index("#toast[hidden]")]
    assert "glow" not in css and "neon" not in css and "gradient" not in css
    hexes = re.findall(r"(?<![\w-])#[0-9a-fA-F]{3,6}\b", css)
    assert hexes == [], hexes                    # only theme variables (AA-checked in test_v091_theme)


def test_non_dev_conversations_are_told_where_their_files_go(env):
    base, h, _ = env()
    a = new_conv(base)
    agent = h.get(a).agent
    assert agent is not None
    h._sync_dev(h.get(a))
    assert f"conversations/{a}/" in agent.extra_rules
