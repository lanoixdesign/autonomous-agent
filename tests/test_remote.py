"""Remote access ("use it from your phone"): QR codes, sessions, pairing, rate limits, CSRF, PWA, tunnels."""
import http.client
import json
import os
import stat
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import i18n, pwa, qr, remote
from agent.harness import Harness, make_server
from agent.llm import MockLLM
from agent.loop import Agent, Budget
from agent.permissions import Permissions
from agent.swarm import SwarmConfig
from agent.tools import default_registry

TOKEN = "t" * 40


# ---------------------------------------------------------------- QR
def finder_ok(m, r, c):
    for i in range(7):
        for j in range(7):
            ring = max(abs(i - 3), abs(j - 3))
            if m[r + i][c + j] != (ring != 2):
                return False
    return True


@pytest.mark.parametrize("text,size", [("hi", 21), ("https://example.ts.net/connect?pair=" + "x" * 24, 33),
                                      ("y" * 200, 57)])
def test_qr_structure(text, size):
    m = qr.encode(text)
    assert len(m) == size and all(len(r) == size for r in m)
    assert finder_ok(m, 0, 0) and finder_ok(m, 0, size - 7) and finder_ok(m, size - 7, 0)
    assert [m[6][i] for i in range(8, size - 8)] == [i % 2 == 0 for i in range(8, size - 8)]   # timing
    assert m[size - 8][8]                                                                       # dark module


def test_qr_limits_and_renderers():
    with pytest.raises(ValueError):
        qr.encode("z" * (qr.MAX_BYTES + 1))
    m = qr.encode("hello")
    svg = qr.to_svg(m, scale=4, quiet=4)
    assert svg.startswith("<svg") and 'viewBox="0 0 116 116"' in svg and svg.endswith("</svg>")
    txt = qr.to_text(m, quiet=2, ansi=False)
    assert len(txt.splitlines()) == (21 + 4 + 1) // 2


def test_qr_decodes_with_opencv():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    for text in ("https://box.tail1234.ts.net/connect?pair=AbC-123_xyz", "é" * 30, "q" * 150):
        m = qr.encode(text)
        img = np.array([[0 if v else 255 for v in row] for row in m], dtype=np.uint8)
        img = np.pad(img, 4, constant_values=255)
        img = cv2.resize(img, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
        assert cv2.QRCodeDetector().detectAndDecode(img)[0] == text


# ---------------------------------------------------------------- Auth
class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_token_and_sessions_expire():
    c = Clock()
    a = remote.Auth(TOKEN, remote=True, session_days=1, clock=c)
    assert a.required and a.check_token(TOKEN) and not a.check_token("nope") and not a.check_token(None)
    sid = a.login("1.2.3.4", token=TOKEN)
    assert a.check_session(sid)
    c.now += 86400 + 1
    assert not a.check_session(sid)
    sid = a.login("1.2.3.4", token=TOKEN)
    a.logout(sid)
    assert not a.check_session(sid)
    with pytest.raises(remote.LoginError):
        a.login("1.2.3.4")                      # nothing given


def test_pairing_is_one_time_and_expires():
    c = Clock()
    a = remote.Auth(TOKEN, remote=True, clock=c)
    code, exp = a.new_pairing()
    assert exp == c.now + remote.PAIR_TTL
    assert a.check_session(a.login("p", pair=code))
    with pytest.raises(remote.LoginError):
        a.login("p", pair=code)                 # used
    code, _ = a.new_pairing()
    c.now += remote.PAIR_TTL + 1
    with pytest.raises(remote.LoginError):
        a.login("p", pair=code)                 # expired


def test_rate_limit_per_client_and_global():
    c = Clock()
    a = remote.Auth(TOKEN, remote=True, clock=c, max_failures=3, window=60, global_failures=5)
    for _ in range(3):
        with pytest.raises(remote.LoginError):
            a.login("a", token="bad")
    with pytest.raises(remote.RateLimited) as e:
        a.login("a", token=TOKEN)               # even the right token waits
    assert 0 < e.value.retry_after <= 61
    for _ in range(2):
        with pytest.raises(remote.LoginError):
            a.login("b", token="bad")
    with pytest.raises(remote.RateLimited):
        a.login("c", token=TOKEN)               # global limit
    c.now += 61
    assert a.login("a", token=TOKEN)


def test_revoke_all_drops_sessions_and_codes():
    a = remote.Auth(TOKEN, remote=True)
    sids = [a.login("x", token=TOKEN) for _ in range(3)]
    code, _ = a.new_pairing()
    assert a.revoke_all() == 3
    assert not any(a.check_session(s) for s in sids)
    with pytest.raises(remote.LoginError):
        a.login("x", pair=code)


def test_cookie_flags():
    a = remote.Auth(TOKEN, remote=True)
    ck = a.cookie("abc", secure=True)
    assert ck.startswith(remote.COOKIE + "=abc;") and "HttpOnly" in ck and "SameSite=Strict" in ck
    assert "Secure" in ck and "Secure" not in a.cookie("abc", secure=False)
    assert "Max-Age=0" in a.clear_cookie(False)
    assert remote.cookie_value("x=1; aa_session=zz; y=2") == "zz" and remote.cookie_value(None) is None


def test_load_or_create_token(tmp_path):
    tok, where = remote.load_or_create_token(tmp_path, env={})
    p = tmp_path / "remote-token"
    assert where == str(p) and len(tok) >= remote.MIN_TOKEN and p.read_text().strip() == tok
    if os.name != "nt":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert remote.load_or_create_token(tmp_path, env={})[0] == tok      # stable
    assert remote.load_or_create_token(tmp_path, env={"AGENT_HARNESS_TOKEN": TOKEN}) == (TOKEN, "AGENT_HARNESS_TOKEN")
    with pytest.raises(ValueError):
        remote.load_or_create_token(tmp_path, env={"AGENT_HARNESS_TOKEN": "short"})


# ---------------------------------------------------------------- HTTP, remote mode
@pytest.fixture
def rserver(ctx, tmp_path):
    started = []

    def start(remote_mode=True, token=TOKEN, local_trusted=True, **auth_kw):
        def factory(task, audit, confirm, cancel, on_event):
            return Agent(MockLLM(), default_registry(enable_web=False, enable_github=False), Permissions(),
                         audit, ctx, Budget(), confirm=confirm, on_event=on_event, swarm=SwarmConfig(),
                         cancel=cancel)
        h = Harness(factory, tmp_path / "state" / "audit.jsonl", workspace=ctx.workspace)
        auth = remote.Auth(token, remote=remote_mode, local_trusted=local_trusted, **auth_kw)
        srv = make_server(h, "127.0.0.1", 0, token, warn=lambda m: None, remote_mode=remote_mode, auth=auth)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append((srv, h))
        return srv.server_address[1], h, auth

    yield start
    for srv, h in started:
        h.shutdown()
        srv.shutdown()
        srv.server_close()


PROXY = {"Host": "box.tail1234.ts.net", "X-Forwarded-For": "100.64.0.7", "X-Forwarded-Proto": "https",
         "X-Forwarded-Host": "box.tail1234.ts.net"}
ORIGIN = {"Origin": "https://box.tail1234.ts.net"}


def req(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    c.request(method, path, body=None if body is None else json.dumps(body), headers=hdrs)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        data = json.loads(raw or b"null")
    except ValueError:
        data = raw
    return r.status, data, r


def test_remote_mode_refuses_proxied_requests_without_auth(rserver):
    port, h, _ = rserver()
    assert req(port, "GET", "/tasks", headers=PROXY)[0] == 401
    assert req(port, "GET", "/tasks", headers={"Host": "evil.example"})[0] == 401          # DNS rebinding
    assert req(port, "GET", "/tasks", headers={"X-Forwarded-For": "1.2.3.4"})[0] == 401
    assert req(port, "GET", "/tasks")[0] == 200                                            # this computer
    assert req(port, "GET", "/tasks", headers={**PROXY, "Authorization": "Bearer " + TOKEN})[0] == 200
    st, s, _ = req(port, "GET", "/auth/status", headers=PROXY)
    assert st == 200 and s["required"] and s["remote"] and not s["authenticated"]
    assert req(port, "GET", "/auth/status")[1]["via"] == "local"
    # pages and PWA assets load without auth (they hold no data); the API does not
    assert req(port, "GET", "/connect", headers=PROXY)[0] == 200
    assert req(port, "GET", "/manifest.webmanifest", headers=PROXY)[0] == 200


def test_local_trust_can_be_disabled(rserver):
    port, _, _ = rserver(local_trusted=False)
    assert req(port, "GET", "/tasks")[0] == 401


def test_pairing_login_sets_secure_cookie_and_works_once(rserver):
    port, h, auth = rserver()
    st, p, _ = req(port, "POST", "/auth/pair", {}, headers={"Origin": "http://127.0.0.1:%d" % port})
    assert st == 200 and "connect?pair=" + p["code"] in p["url"] and p["svg"].startswith("<svg")
    assert 0 < p["expires_in"] <= remote.PAIR_TTL
    st, _, r = req(port, "POST", "/auth/login", {"pair": p["code"]}, headers={**PROXY, **ORIGIN})
    ck = r.getheader("Set-Cookie")
    assert st == 200 and "HttpOnly" in ck and "SameSite=Strict" in ck and "Secure" in ck
    sid = remote.cookie_value(ck)
    cookie = {"Cookie": f"{remote.COOKIE}={sid}"}
    assert req(port, "GET", "/tasks", headers={**PROXY, **cookie})[0] == 200
    assert req(port, "GET", "/auth/status", headers={**PROXY, **cookie})[1]["via"] == "cookie"
    # the same code cannot be used twice
    assert req(port, "POST", "/auth/login", {"pair": p["code"]}, headers={**PROXY, **ORIGIN})[0] == 401
    # cookie POSTs: same origin only, and an Origin is required
    assert req(port, "POST", "/tasks", {"task": "x"}, headers={**PROXY, **cookie, **ORIGIN})[0] == 201
    assert req(port, "POST", "/tasks", {"task": "x"}, headers={**PROXY, **cookie})[0] == 403
    assert req(port, "POST", "/tasks", {"task": "x"},
               headers={**PROXY, **cookie, "Origin": "https://evil.example"})[0] == 403
    assert req(port, "POST", "/tasks", {"task": "x"},
               headers={**PROXY, **cookie, **ORIGIN, "Content-Type": "text/plain"})[0] == 415
    # logout ends the session
    st, _, r = req(port, "POST", "/auth/logout", {}, headers={**PROXY, **cookie, **ORIGIN})
    assert st == 200 and "Max-Age=0" in r.getheader("Set-Cookie")
    assert req(port, "GET", "/tasks", headers={**PROXY, **cookie})[0] == 401


def test_token_login_plain_http_cookie_not_secure_and_rate_limited(rserver):
    port, _, _ = rserver(max_failures=2, window=60)
    hdr = {"X-Forwarded-For": "100.64.0.9", "Host": "box.lan:8765", "Origin": "http://box.lan:8765"}
    st, _, r = req(port, "POST", "/auth/login", {"token": TOKEN}, headers=hdr)
    assert st == 200 and "Secure" not in r.getheader("Set-Cookie")
    for _ in range(2):
        assert req(port, "POST", "/auth/login", {"token": "wrong"}, headers=hdr)[0] == 401
    st, _, r = req(port, "POST", "/auth/login", {"token": TOKEN}, headers=hdr)
    assert st == 429 and int(r.getheader("Retry-After")) > 0
    # another client is not affected
    other = {**hdr, "X-Forwarded-For": "100.64.0.10"}
    assert req(port, "POST", "/auth/login", {"token": TOKEN}, headers=other)[0] == 200
    # cross-site login form refused
    assert req(port, "POST", "/auth/login", {"token": TOKEN},
               headers={**other, "Origin": "https://evil.example"})[0] == 403


def test_revoke_all_over_http(rserver):
    port, _, auth = rserver()
    sid = auth.login("x", token=TOKEN)
    cookie = {"Cookie": f"{remote.COOKIE}={sid}"}
    assert req(port, "POST", "/auth/revoke-all", {}, headers={**PROXY, **cookie})[0] == 403    # no Origin
    st, body, _ = req(port, "POST", "/auth/revoke-all", {}, headers={**PROXY, **cookie, **ORIGIN})
    assert st == 200 and body["sessions"] == 1
    assert req(port, "GET", "/tasks", headers={**PROXY, **cookie})[0] == 401


def test_make_server_refuses_without_token(ctx, tmp_path):
    h = Harness(lambda *a: None, tmp_path / "a.jsonl")
    with pytest.raises(ValueError):
        make_server(h, "127.0.0.1", 0, None, warn=lambda m: None, remote_mode=True)
    srv = make_server(h, "127.0.0.1", 0, None, warn=lambda m: None)        # plain local use stays open
    srv.server_close()


# ---------------------------------------------------------------- PWA
def test_pwa_assets(rserver):
    port, _, _ = rserver()
    st, man, r = req(port, "GET", "/manifest.webmanifest")
    assert st == 200 and man["display"] == "standalone" and man["start_url"]
    assert {i["sizes"] for i in man["icons"]} >= {"192x192", "512x512"}
    st, body, r = req(port, "GET", "/sw.js")
    sw = body.decode() if isinstance(body, bytes) else str(body)
    assert st == 200 and "javascript" in r.getheader("Content-Type")
    for p in ("/tasks", "/approvals", "/auth", "/stream", "/settings"):
        assert p not in pwa.SHELL
    assert "pair=" in sw
    st, png, r = req(port, "GET", "/icon-192.png")
    assert st == 200 and png[:8] == b"\x89PNG\r\n\x1a\n" and r.getheader("Content-Type") == "image/png"
    st, page, _ = req(port, "GET", "/chat")
    page = page.decode()
    assert st == 200 and 'rel="manifest"' in page and "serviceWorker" in page and "viewport-fit=cover" in page


def test_api_is_never_cacheable(rserver):
    port, _, _ = rserver()
    for path in ("/tasks", "/approvals", "/auth/status"):
        assert req(port, "GET", path)[2].getheader("Cache-Control") == "no-store"
    assert req(port, "GET", "/connect")[2].getheader("Referrer-Policy") == "no-referrer"


# ---------------------------------------------------------------- CLI banner, tunnels
def test_remote_banner_prints_qr_for_public_url(rserver, capsys, monkeypatch):
    from agent.cli import remote_banner
    port, h, auth = rserver()
    monkeypatch.delenv("AGENT_REMOTE_URL", raising=False)
    monkeypatch.delenv("AGENT_TUNNEL", raising=False)
    monkeypatch.delenv("AGENT_QR", raising=False)
    args = SimpleNamespace(lang="en", public_url="https://box.tail1234.ts.net", tunnel=None, no_qr=False)
    assert remote_banner(args, h, auth, "127.0.0.1", port, "AGENT_HARNESS_TOKEN", False) is None
    err = capsys.readouterr().err
    assert "https://box.tail1234.ts.net/connect?pair=" in err and ("\u2580" in err or "\u2584" in err)
    assert h.public_url == "https://box.tail1234.ts.net/"
    assert TOKEN not in err                     # the master token is never printed
    args.no_qr = True
    remote_banner(args, h, auth, "127.0.0.1", port, "x", False)
    assert "\u2584" not in capsys.readouterr().err


def fake_exe(dirpath, name, script):
    p = Path(dirpath) / name
    if os.name == "nt":
        pytest.skip("fake executables use a shebang")
    p.write_text(f"#!{sys.executable}\n" + script)
    p.chmod(0o755)
    return p


def test_tunnels_with_fake_tools(tmp_path, monkeypatch):
    fake_exe(tmp_path, "tailscale", "import sys, json\n"
             "if sys.argv[1:3] == ['status', '--json']:\n"
             "    print(json.dumps({'BackendState': 'Running', 'Self': {'DNSName': 'box.tail1234.ts.net.'}}))\n"
             "elif sys.argv[1] == 'serve':\n    print('ok')\n")
    fake_exe(tmp_path, "cloudflared", "import sys, time\n"
             "print('INF Requesting new quick Tunnel', flush=True)\n"
             "print('INF |  https://shy-cat-42.trycloudflare.com  |', flush=True)\n"
             "time.sleep(30)\n")
    monkeypatch.setenv("PATH", str(tmp_path))
    found = {d["tool"]: d for d in remote.detect(8765)}
    assert found["tailscale"]["url"] == "https://box.tail1234.ts.net/"
    assert "cloudflared tunnel --url http://127.0.0.1:8765" == found["cloudflared"]["command"]
    assert remote.start_tunnel("tailscale", 8765) == ("https://box.tail1234.ts.net/", None)
    url, proc = remote.start_tunnel("cloudflared", 8765, timeout=10)
    try:
        assert url == "https://shy-cat-42.trycloudflare.com/"
    finally:
        proc.terminate()
        proc.wait(5)
    with pytest.raises(ValueError):
        remote.start_tunnel("ngrok", 8765)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert remote.detect(8765) == []
    with pytest.raises(RuntimeError):
        remote.start_tunnel("cloudflared", 8765)


def test_remote_strings_bilingual():
    keys = [k for k in i18n.EN if k.startswith(("connect.", "cli.remote."))]
    assert len(keys) > 15 and all(k in i18n.FR and i18n.FR[k] for k in keys)
