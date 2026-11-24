"""v0.9.13: one running copy of the app at a time, across upgrades.

Why: the server keeps running after the browser tab is closed. When a new version was double-clicked, the old
launcher logic only opened the browser on the copy already running, so the user kept seeing (or not seeing)
the OLD version and thought the new one did not start.

- `data/instance.json` records the running copy: pid, port, version and a random stop token (file 0600).
- `find()` looks for a copy on the recorded port, then on the usual port: same version -> open it;
  other version -> `stop()` asks it to quit (stop token, else the page's own Quit button API, which old
  versions have too), waits, and as a last resort ends the recorded process. A file left by a crash
  (process gone, nothing answering) is removed ("stale").
- Something else on the port: the launcher simply uses another free port.
"""
from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

FILE = "instance.json"
TOKEN_HEADER = "X-Instance-Token"
TOKEN_ENV = "AGENT_INSTANCE_TOKEN"


def path(data_dir: Path) -> Path:
    return Path(data_dir) / FILE


def read(data_dir: Path) -> dict | None:
    try:
        d = json.loads(path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def write(data_dir: Path, port: int, version: str, token: str) -> None:
    p = path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "port": port, "version": version, "token": token,
                   "started": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
    os.replace(tmp, p)


def remove(data_dir: Path, only_pid: int | None = None) -> None:
    d = read(data_dir)
    if only_pid is not None and d is not None and d.get("pid") != only_pid:
        return            # another copy took over: its file stays
    try:
        path(data_dir).unlink()
    except OSError:
        pass


def new_token() -> str:
    return secrets.token_urlsafe(24)


def pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                                 timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            return str(pid) in out
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _get(url: str, timeout: float) -> tuple[int, dict, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, json.loads(r.read(65536) or b"{}"), r.headers.get("Server") or ""
    except urllib.error.HTTPError as e:
        return e.code, {}, e.headers.get("Server") or ""


def probe(port: int, timeout: float = 1.5) -> dict | None:
    """{"port", "url", "version"} if an autonomous-agent answers on 127.0.0.1:port, else None.
    version is None when it cannot be read (sign-in required)."""
    base = f"http://127.0.0.1:{port}/"
    try:
        st, data, server = _get(base + "health", timeout)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if "autonomous-agent" not in server:
        return None
    version = data.get("version") if st == 200 and isinstance(data.get("version"), str) else None
    return {"port": port, "url": base, "version": version, "stopping": data.get("status") == "stopping"}


def find(data_dir: Path, ports: list[int], log: Callable[[str], None] = lambda m: None) -> dict | None:
    """The running copy (recorded one first), with its record if it matches; removes a stale record."""
    rec = read(data_dir)
    cands = []
    if rec and isinstance(rec.get("port"), int):
        cands.append(rec["port"])
    cands += [p for p in ports if p not in cands]
    for port in cands:
        info = probe(port)
        if info is None:
            continue
        if rec and rec.get("port") == port and pid_alive(rec.get("pid")):
            info["record"] = rec
            if info["version"] is None:
                info["version"] = rec.get("version")
        return info
    if rec is not None:
        log(f"instance: stale {FILE} removed (pid {rec.get('pid')} port {rec.get('port')}: nothing answers)")
        remove(data_dir)
    return None


def _post(url: str, headers: dict, timeout: float) -> int:
    req = urllib.request.Request(url, data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def ask_quit(info: dict, timeout: float = 3.0) -> bool:
    """Ask the running copy to quit: stop token (0.9.13+), else the Quit button API (0.9.x)."""
    base, origin = info["url"], info["url"].rstrip("/")
    rec = info.get("record") or {}
    try:
        if rec.get("token"):
            if _post(base + "app/takeover", {TOKEN_HEADER: rec["token"], "Origin": origin}, timeout) in (200, 202):
                return True
        csrf = ""
        try:
            st, data, _ = _get(base + "app/status", timeout)
            csrf = str(data.get("csrf") or "") if st == 200 else ""
        except (urllib.error.URLError, OSError, ValueError):
            pass
        return _post(base + "app/quit", {"X-CSRF-Token": csrf, "Origin": origin}, timeout) in (200, 202)
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wait_gone(port: int, seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if probe(port, timeout=1.0) is None:
            return True
        time.sleep(0.3)
    return probe(port, timeout=1.0) is None


def kill(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        os.kill(pid, signal.SIGTERM)


def stop(info: dict, log: Callable[[str], None] = lambda m: None, wait: float = 10.0) -> bool:
    """Stop the other copy. True when its port is free again."""
    asked = ask_quit(info)
    log(f"instance: asked version {info.get('version') or '?'} on port {info['port']} to quit: {asked}")
    if wait_gone(info["port"], wait if asked else 1.0):
        return True
    pid = (info.get("record") or {}).get("pid")
    if isinstance(pid, int) and pid != os.getpid() and pid_alive(pid):
        log(f"instance: ending process {pid}")
        try:
            kill(pid)
        except (OSError, subprocess.SubprocessError) as e:
            log(f"instance: could not end {pid}: {e}")
        return wait_gone(info["port"], 5.0)
    return False
