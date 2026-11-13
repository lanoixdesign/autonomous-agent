"""Remote access for the harness ("use it from your phone"): sessions, pairing codes, rate limits, tunnels.

Model:
- `--remote` (or AGENT_REMOTE=1) makes authentication mandatory for every API call that does not come
  straight from this computer. The master token is AGENT_HARNESS_TOKEN (>= 24 characters) or a random
  one generated once and kept in <state-dir>/remote-token (mode 0600).
- A phone logs in once, with the token or with a ONE-TIME pairing code (QR code, valid 10 minutes), and gets
  a session cookie: HttpOnly, SameSite=Strict, Secure when the request came through HTTPS.
- Failed logins are rate limited (per client and globally). POSTs authenticated by cookie must come from
  the same origin (Origin header), and every POST must be JSON: a cross-site form cannot do either.
- The recommended way in is a private tunnel that adds HTTPS: Tailscale (`tailscale serve`) or Cloudflare
  Tunnel (`cloudflared tunnel --url`). The harness keeps listening on 127.0.0.1.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

COOKIE = "aa_session"
MIN_TOKEN = 24
PAIR_TTL = 600.0
FORWARD_HEADERS = ("X-Forwarded-For", "Forwarded", "X-Real-IP", "Cf-Connecting-Ip", "Tailscale-User-Login",
                   "X-Forwarded-Host", "X-Forwarded-Proto")


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        super().__init__(f"too many failed attempts; retry in {retry_after}s")
        self.retry_after = retry_after


class LoginError(Exception):
    pass


def load_or_create_token(state_dir: Path, env: dict | None = None) -> tuple[str, str]:
    """(token, where): AGENT_HARNESS_TOKEN if set (must be strong), else <state-dir>/remote-token."""
    env = os.environ if env is None else env
    tok = (env.get("AGENT_HARNESS_TOKEN") or "").strip()
    if tok:
        if len(tok) < MIN_TOKEN:
            raise ValueError(f"remote mode: AGENT_HARNESS_TOKEN must be at least {MIN_TOKEN} characters "
                             "(or unset it and a strong one will be generated)")
        return tok, "AGENT_HARNESS_TOKEN"
    path = Path(state_dir) / "remote-token"
    if path.is_file():
        tok = path.read_text(encoding="utf-8").strip()
        if len(tok) >= MIN_TOKEN:
            return tok, str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tok = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(tok + "\n")
    return tok, str(path)


class Auth:
    """Token, cookie sessions, one-time pairing codes and login rate limits (all in memory)."""

    def __init__(self, token: str | None, remote: bool = False, session_days: float = 30.0,
                 max_failures: int = 10, window: float = 300.0, global_failures: int = 50,
                 clock: Callable[[], float] = time.time, local_trusted: bool = True):
        self.token = token or None
        self.remote = remote
        self.session_ttl = session_days * 86400
        self.max_failures, self.window, self.global_failures = max_failures, window, global_failures
        self.clock = clock
        self.local_trusted = local_trusted
        self._sessions: dict[str, float] = {}
        self._pairs: dict[str, float] = {}
        self._fails: dict[str, list[float]] = {}
        self._all_fails: list[float] = []
        self._lock = threading.Lock()

    @property
    def required(self) -> bool:
        return self.token is not None

    def check_token(self, value: str | None) -> bool:
        return bool(self.token and value) and hmac.compare_digest(value.encode(), self.token.encode())

    # -- sessions
    def check_session(self, sid: str | None) -> bool:
        if not sid:
            return False
        now = self.clock()
        with self._lock:
            exp = self._sessions.get(sid)
            if exp is None:
                return False
            if exp < now:
                del self._sessions[sid]
                return False
            return True

    def logout(self, sid: str | None) -> None:
        with self._lock:
            self._sessions.pop(sid or "", None)

    def revoke_all(self) -> int:
        with self._lock:
            n = len(self._sessions)
            self._sessions.clear()
            self._pairs.clear()
            return n

    # -- pairing (one-time codes for the QR code)
    def new_pairing(self, ttl: float = PAIR_TTL) -> tuple[str, float]:
        code = secrets.token_urlsafe(18)
        exp = self.clock() + ttl
        with self._lock:
            now = self.clock()
            self._pairs = {c: e for c, e in self._pairs.items() if e > now}
            self._pairs[code] = exp
        return code, exp

    # -- login
    def _check_rate(self, client: str, now: float) -> None:
        recent = [t for t in self._fails.get(client, []) if t > now - self.window]
        self._fails[client] = recent
        self._all_fails = [t for t in self._all_fails if t > now - self.window]
        if len(recent) >= self.max_failures:
            raise RateLimited(int(recent[0] + self.window - now) + 1)
        if len(self._all_fails) >= self.global_failures:
            raise RateLimited(int(self._all_fails[0] + self.window - now) + 1)

    def login(self, client: str, token: str | None = None, pair: str | None = None) -> str:
        """Returns a new session id, or raises RateLimited / LoginError. A pairing code works once."""
        now = self.clock()
        with self._lock:
            self._check_rate(client, now)
            ok = False
            if pair:
                exp = self._pairs.pop(str(pair), None)       # one time, valid or not
                ok = exp is not None and exp > now
            elif token is not None:
                ok = self.check_token(str(token))
            if not ok:
                self._fails.setdefault(client, []).append(now)
                self._all_fails.append(now)
                raise LoginError("invalid or expired token / pairing code")
            self._fails.pop(client, None)
            sid = secrets.token_urlsafe(32)
            self._sessions[sid] = now + self.session_ttl
            return sid

    def cookie(self, sid: str, secure: bool) -> str:
        return (f"{COOKIE}={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age={int(self.session_ttl)}"
                + ("; Secure" if secure else ""))

    def clear_cookie(self, secure: bool) -> str:
        return f"{COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" + ("; Secure" if secure else "")


def cookie_value(header: str | None, name: str = COOKIE) -> str | None:
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == name and v:
            return v
    return None


# ---------------------------------------------------------------- tunnels and public URL
def lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))          # TEST-NET address: nothing is sent
            return s.getsockname()[0]
    except OSError:
        return None


def tailscale_info(run: Callable = subprocess.run) -> dict | None:
    """{'dns': 'machine.tailnet.ts.net'} if the tailscale CLI is installed and logged in, else None."""
    exe = shutil.which("tailscale")
    if not exe:
        return None
    try:
        r = run([exe, "status", "--json"], capture_output=True, text=True, timeout=5)
        data = json.loads(r.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"dns": None, "exe": exe}
    dns = ((data.get("Self") or {}).get("DNSName") or "").rstrip(".") or None
    return {"dns": dns, "exe": exe, "state": data.get("BackendState")}


def detect(port: int) -> list[dict]:
    """Which tunnel tools are installed, with the command to use and the URL when it can be known."""
    out = []
    ts = tailscale_info()
    if ts is not None:
        out.append({"tool": "tailscale", "command": f"tailscale serve --bg {port}",
                    "url": f"https://{ts['dns']}/" if ts.get("dns") else None})
    if shutil.which("cloudflared"):
        out.append({"tool": "cloudflared", "command": f"cloudflared tunnel --url http://127.0.0.1:{port}",
                    "url": None})
    return out


_TRYCF = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def start_tunnel(kind: str, port: int, timeout: float = 30.0, popen: Callable = subprocess.Popen,
                 run: Callable = subprocess.run) -> tuple[str | None, object | None]:
    """Start a tunnel on request. Returns (public https URL or None, process to stop on exit or None).

    tailscale: `tailscale serve --bg PORT` (HTTPS inside your tailnet only; stays configured until
    `tailscale serve --https=443 off`). cloudflared: a quick tunnel with a random trycloudflare.com URL,
    stopped with the harness."""
    if kind == "tailscale":
        ts = tailscale_info(run)
        if ts is None:
            raise RuntimeError("tailscale is not installed (https://tailscale.com/download)")
        r = run([ts["exe"], "serve", "--bg", str(port)], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError("tailscale serve failed: " + (r.stderr or r.stdout or "").strip()[:300])
        return (f"https://{ts['dns']}/" if ts.get("dns") else None), None
    if kind == "cloudflared":
        exe = shutil.which("cloudflared")
        if not exe:
            raise RuntimeError("cloudflared is not installed (https://developers.cloudflare.com/cloudflare-one/"
                               "connections/connect-networks/downloads/)")
        proc = popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        found: list[str] = []

        def reader() -> None:
            for line in proc.stdout:
                m = _TRYCF.search(line)
                if m and not found:
                    found.append(m.group(0) + "/")
        threading.Thread(target=reader, daemon=True).start()
        end = time.monotonic() + timeout
        while time.monotonic() < end and not found and proc.poll() is None:
            time.sleep(0.1)
        return (found[0] if found else None), proc
    raise ValueError("tunnel must be tailscale or cloudflared")
