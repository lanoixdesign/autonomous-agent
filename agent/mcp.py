"""MCP (Model Context Protocol) connector, pure Python (stdlib only). v0.9.8: really wired into the agents.

The user adds a "service" in the Connect tab (a ready-made preset, or a web address, or — advanced — a local
program). Its tools become agent tools named ``mcp_<server>_<tool>``:

  * tools the server marks ``readOnlyHint`` follow the "read" rules (allowed by default);
  * every other tool asks the user first (approval card), like the rest of the app;
  * results are fenced in ``<external_content>`` (data, never instructions) and redacted;
  * every call goes through the agent loop, so it gets its own line in ``audit.jsonl``.

Servers start lazily (on the first call, or when the user clicks "Test"), every request has a timeout, a
server that fails never breaks the chat (the model gets a plain sentence instead), and all processes are
stopped when the app quits. Tokens and environment values are stored like API keys (SecretStore: keychain or
a 0600 file), only ever shown masked. Transports: stdio (newline-delimited JSON-RPC 2.0) and Streamable HTTP
(JSON or SSE answers, ``Mcp-Session-Id``).
"""
from __future__ import annotations

import atexit
import glob
import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import weakref
from pathlib import Path
from typing import Any, Callable

from .redact import redact
from .tools import Tool, ToolContext, ToolError

PROTOCOL_VERSION = "2025-06-18"
CONNECT_TIMEOUT = 60.0      # first start of an `npx` server may download it
CALL_TIMEOUT = 45.0
MAX_OUTPUT = 6000           # characters of one result given to the model (Groq free tier: 8K tokens/minute)
MAX_TOOLS_SENT = 8          # MCP tools described to the model per request (the most relevant ones)
DESC_CHARS = 160
PARAM_DESC_CHARS = 70
NAME_RE = re.compile(r"^[^\x00-\x1f<>\"`]{1,40}$")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
TOOL_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")
RETRY_AFTER_FAIL = 120.0    # a server that failed to start is not retried for every message

# what a command needs installed, and where a beginner gets it
RUNTIMES = {"npx": "node", "node": "node", "npm": "node", "uvx": "uv", "uv": "uv", "python": "python",
            "python3": "python", "py": "python", "docker": "docker", "deno": "deno", "bun": "bun"}
PROGRAM_NAMES = {"node": "Node.js", "uv": "uv", "python": "Python", "docker": "Docker Desktop", "deno": "Deno",
                 "bun": "Bun"}
INSTALL_LINKS = {"node": "https://nodejs.org/", "uv": "https://docs.astral.sh/uv/getting-started/installation/",
                 "python": "https://www.python.org/downloads/", "docker": "https://www.docker.com/products/docker-desktop/",
                 "deno": "https://deno.com/", "bun": "https://bun.sh/"}

# Ready-made services: the user types at most one thing (a folder, a token).
PRESETS = {
    "files": {"name": {"en": "My files", "fr": "Mes fichiers"}, "transport": "stdio", "needs": "folder",
              "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem"], "runtime": "node"},
    "github": {"name": {"en": "GitHub", "fr": "GitHub"}, "transport": "http", "needs": "token",
               "url": "https://api.githubcopilot.com/mcp/",
               "token_link": "https://github.com/settings/personal-access-tokens/new"},
    "web": {"name": {"en": "", "fr": ""}, "transport": "http", "needs": "url"},
}

# minimal environment given to a local server (never the app's own keys)
SAFE_ENV = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP", "SHELL", "USERPROFILE",
            "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "ProgramFiles", "ProgramFiles(x86)", "SystemRoot", "SystemDrive",
            "WINDIR", "COMSPEC", "PATHEXT", "HOMEDRIVE", "HOMEPATH", "XDG_RUNTIME_DIR", "NVM_DIR", "VOLTA_HOME")

# tool name -> (service name, plain title): the chat says "used GitHub: List issues"
LABELS: dict[str, tuple[str, str]] = {}


class MCPError(Exception):
    """`code` is stable (shown in plain words by the page), `params` fill the sentence."""

    def __init__(self, code: str, message: str = "", **params: Any):
        super().__init__(message or code)
        self.code, self.params = code, params


# ----------------------------------------------------------------------------- helpers
def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "", s)[:20]
    return s or "srv"


def _extra_dirs() -> list[str]:
    """Where installers put node / npx / uvx when an app started from the Finder has a short PATH."""
    home = os.path.expanduser("~")
    dirs = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", os.path.join(home, ".local", "bin"),
            os.path.join(home, ".cargo", "bin"), os.path.join(home, ".volta", "bin"), os.path.join(home, ".bun", "bin"),
            os.path.join(home, ".deno", "bin")]
    dirs += sorted(glob.glob(os.path.join(home, ".nvm", "versions", "node", "*", "bin")), reverse=True)
    if os.name == "nt":
        for var, sub in (("ProgramFiles", "nodejs"), ("APPDATA", "npm"), ("LOCALAPPDATA", r"Programs\Python"),
                         ("USERPROFILE", r".local\bin")):
            if os.environ.get(var):
                dirs.append(os.path.join(os.environ[var], sub))
    return [d for d in dirs if os.path.isdir(d)]


def search_path() -> str:
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    for d in _extra_dirs():
        if d not in parts:
            parts.append(d)
    return os.pathsep.join(parts)


def find_program(cmd: str) -> str | None:
    if os.path.isabs(cmd) or os.sep in cmd:
        return cmd if os.path.exists(cmd) else None
    return shutil.which(cmd, path=search_path())


def split_command(command: Any) -> list[str]:
    if isinstance(command, list):
        return [str(x) for x in command]
    try:
        argv = shlex.split(str(command or ""), posix=os.name != "nt")
    except ValueError as e:
        raise MCPError("bad_command", f"command: {e}")
    return [a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a for a in argv]   # Windows keeps the quotes


def missing_program(argv: list[str]) -> MCPError | None:
    """A plain reason when the command cannot start: 'Node.js is not installed' + where to get it."""
    if not argv:
        return MCPError("bad_command", "empty command")
    exe = os.path.basename(argv[0]).lower()
    for ext in (".exe", ".cmd", ".bat"):
        if exe.endswith(ext):
            exe = exe[: -len(ext)]
    if find_program(argv[0]):
        rt = RUNTIMES.get(exe)
        if rt == "node" and exe == "npx" and not find_program("node"):
            return MCPError("needs_program", "Node.js is not installed", program=PROGRAM_NAMES["node"],
                            link=INSTALL_LINKS["node"])
        return None
    rt = RUNTIMES.get(exe)
    if rt:
        return MCPError("needs_program", f"{PROGRAM_NAMES[rt]} is not installed", program=PROGRAM_NAMES[rt],
                        link=INSTALL_LINKS[rt])
    return MCPError("not_found", f"program not found: {argv[0]}", program=argv[0][:60])


def _clip(text: Any, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def compact_schema(schema: Any, depth: int = 0) -> dict:
    """Keep what the model needs to call the tool, drop the rest (titles, examples, $schema...)."""
    if not isinstance(schema, dict):
        return {"type": "string"}
    out: dict = {}
    typ = schema.get("type")
    if isinstance(typ, list):
        typ = next((x for x in typ if x != "null"), "string")
    if typ:
        out["type"] = typ
    elif "properties" in schema:
        out["type"] = "object"
    if schema.get("description") and depth > 0:
        out["description"] = _clip(schema["description"], PARAM_DESC_CHARS)
    if isinstance(schema.get("enum"), list):
        out["enum"] = schema["enum"][:12]
    if depth >= 3:
        if out.get("type") == "object":
            out.pop("properties", None)
        return out or {"type": "string"}
    if isinstance(schema.get("properties"), dict):
        out["type"] = "object"
        out["properties"] = {str(k): compact_schema(v, depth + 1) for k, v in list(schema["properties"].items())[:20]}
        req = [r for r in (schema.get("required") or []) if r in out["properties"]]
        if req:
            out["required"] = req
    elif out.get("type") == "object" and depth == 0:
        out["properties"] = {}
    if isinstance(schema.get("items"), dict):
        out["items"] = compact_schema(schema["items"], depth + 1)
    elif out.get("type") == "array":
        out["items"] = {"type": "string"}
    for alt in ("anyOf", "oneOf"):
        if not out.get("type") and isinstance(schema.get(alt), list) and schema[alt]:
            first = next((x for x in schema[alt] if isinstance(x, dict) and x.get("type") != "null"), schema[alt][0])
            out.update(compact_schema(first, depth))
    return out or {"type": "string"}


def compact_tool(t: dict) -> dict | None:
    """What we keep of one server tool (cached in mcp.json, so the app can describe it without starting it)."""
    if not isinstance(t, dict) or not t.get("name"):
        return None
    ann = t.get("annotations") if isinstance(t.get("annotations"), dict) else {}
    schema = compact_schema(t.get("inputSchema") or {"type": "object"})
    schema["type"] = "object"
    schema.setdefault("properties", {})
    title = t.get("title") or ann.get("title") or str(t["name"]).replace("_", " ").replace("-", " ").strip().capitalize()
    return {"name": str(t["name"])[:120], "title": _clip(title, 60), "description": _clip(t.get("description") or title, DESC_CHARS),
            "read_only": ann.get("readOnlyHint") is True, "schema": schema}


def fence(service: str, text: str) -> str:
    text = text.replace("</external_content>", "</external_content_>")   # cannot close the fence early
    return f"<external_content source=\"{_clip(service, 40)}\">\n{text}\n</external_content>"


def result_text(result: dict) -> str:
    parts = []
    for c in result.get("content") or []:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "text":
            parts.append(str(c.get("text", "")))
        elif c.get("type") == "resource" and isinstance(c.get("resource"), dict):
            r = c["resource"]
            parts.append(str(r.get("text") or f"[file {r.get('uri', '')}]"))
        elif c.get("type") == "resource_link":
            parts.append(f"[link {c.get('name') or ''} {c.get('uri') or ''}]")
        else:
            parts.append(f"[{c.get('type', 'content')}]")
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False)[:MAX_OUTPUT])
    text = "\n".join(parts).strip() or "(empty result)"
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + f"\n[... cut: {len(text) - MAX_OUTPUT} more characters]"
    return text


# ----------------------------------------------------------------------------- client
class MCPClient:
    """One connection to one MCP server (stdio or Streamable HTTP). Thread-safe; lazy."""

    def __init__(self, config: dict, secrets: dict | None = None, connect_timeout: float = CONNECT_TIMEOUT,
                 call_timeout: float = CALL_TIMEOUT):
        self.config = config
        self.name = str(config.get("name") or "MCP")
        self.transport = config.get("transport", "stdio")
        self.secrets = secrets or {}           # {"token": str, "env": {NAME: value}}
        self.connect_timeout, self.call_timeout = connect_timeout, call_timeout
        self.tools: list[dict] = []
        self.server_info: dict = {}
        self.ready = False
        self._proc: subprocess.Popen | None = None
        self._pending: dict[int, queue.Queue] = {}
        self._id = 0
        self._lock = threading.RLock()       # connect / close
        self._wlock = threading.Lock()       # stdin writes, ids
        self._stderr: list[str] = []
        self._session: str | None = None
        self._proto = PROTOCOL_VERSION

    # -- secrets never leave this object except to the server itself
    def secret_values(self) -> list[str]:
        vals = [self.secrets.get("token") or ""] + list((self.secrets.get("env") or {}).values())
        return [v for v in vals if isinstance(v, str) and len(v) >= 4]

    def scrub(self, text: Any) -> Any:
        return redact(text, self.secret_values())

    # -- lifecycle
    def connect(self) -> list[dict]:
        with self._lock:
            if self.ready and (self.transport != "stdio" or self._alive()):
                return self.tools
            self.close()
            try:
                if self.transport == "stdio":
                    self._start_stdio()
                elif self.transport != "http":
                    raise MCPError("bad_config", f"unknown transport {self.transport!r}")
                res = self.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                                  "clientInfo": {"name": "autonomous-agent", "version": _version()}},
                                   timeout=self.connect_timeout)
                self.server_info = res.get("serverInfo") or {}
                if isinstance(res.get("protocolVersion"), str):
                    self._proto = res["protocolVersion"]
                self.notify("notifications/initialized")
                tools, cursor = [], None
                for _ in range(10):
                    page = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout=self.connect_timeout)
                    tools += [t for t in page.get("tools") or [] if isinstance(t, dict)]
                    cursor = page.get("nextCursor")
                    if not cursor:
                        break
                self.tools = tools
                self.ready = True
                return tools
            except MCPError:
                self.close()
                raise
            except Exception as e:  # noqa: BLE001
                self.close()
                raise MCPError("protocol", f"{type(e).__name__}: {e}")

    def close(self) -> None:
        with self._lock:
            self.ready = False
            p, self._proc = self._proc, None
            if p is not None:
                try:
                    if p.stdin:
                        p.stdin.close()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    p.terminate()
                    p.wait(timeout=3)
                except Exception:  # noqa: BLE001
                    try:
                        p.kill()
                    except Exception:  # noqa: BLE001
                        pass
            if self.transport == "http" and self._session:
                try:
                    self._http(None, method="DELETE", timeout=3)
                except Exception:  # noqa: BLE001
                    pass
            self._session = None
            for q in list(self._pending.values()):
                q.put({"_closed": True})
            self._pending.clear()

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # -- stdio
    def _env(self) -> dict:
        env = {k: os.environ[k] for k in SAFE_ENV if k in os.environ}
        env["PATH"] = search_path()
        for k, v in (self.config.get("env_plain") or {}).items():
            if ENV_NAME_RE.match(str(k)):
                env[str(k)] = str(v)
        for k, v in (self.secrets.get("env") or {}).items():
            if ENV_NAME_RE.match(str(k)) and isinstance(v, str):
                env[str(k)] = v
        return env

    def _start_stdio(self) -> None:
        argv = split_command(self.config.get("command"))
        bad = missing_program(argv)
        if bad is not None:
            raise bad
        argv[0] = find_program(argv[0]) or argv[0]
        kw: dict[str, Any] = {}
        if os.name == "nt":
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kw["start_new_session"] = True
        try:
            self._proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          env=self._env(), cwd=os.path.expanduser("~"), text=True, encoding="utf-8",
                                          errors="replace", bufsize=1, **kw)
        except OSError as e:
            raise MCPError("not_found", str(e), program=os.path.basename(argv[0])[:60])
        self._stderr = []
        threading.Thread(target=self._read_stdout, args=(self._proc,), daemon=True, name=f"mcp-{slug(self.name)}").start()
        threading.Thread(target=self._read_stderr, args=(self._proc,), daemon=True).start()

    def _read_stdout(self, proc: subprocess.Popen) -> None:
        try:
            for line in proc.stdout:            # type: ignore[union-attr]
                line = line.strip()
                if not line.startswith("{"):
                    continue                    # a log line printed on stdout: ignore
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                self._dispatch(msg)
        except Exception:  # noqa: BLE001
            pass
        for q in list(self._pending.values()):
            q.put({"_closed": True})

    def _read_stderr(self, proc: subprocess.Popen) -> None:
        try:
            for line in proc.stderr:            # type: ignore[union-attr]
                self._stderr.append(line.rstrip()[:300])
                del self._stderr[:-20]
        except Exception:  # noqa: BLE001
            pass

    def _dispatch(self, msg: Any) -> None:
        if not isinstance(msg, dict):
            return
        if "method" in msg and "id" in msg:      # a request from the server (ping...): answer politely
            reply = ({"jsonrpc": "2.0", "id": msg["id"], "result": {}} if msg["method"] == "ping" else
                     {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "not supported"}})
            try:
                self._write(reply)
            except Exception:  # noqa: BLE001
                pass
            return
        q = self._pending.get(msg.get("id")) if "id" in msg else None
        if q is not None:
            q.put(msg)

    def _write(self, msg: dict) -> None:
        p = self._proc
        if p is None or p.stdin is None or p.poll() is not None:
            raise MCPError("crashed", "the program stopped", detail=self.stderr_tail())
        with self._wlock:
            p.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            p.stdin.flush()

    def stderr_tail(self) -> str:
        return self.scrub(" | ".join(self._stderr[-3:]))[:300]

    # -- http
    def _http(self, msg: dict | None, method: str = "POST", timeout: float | None = None) -> dict | None:
        url = str(self.config.get("url") or "")
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                   "MCP-Protocol-Version": self._proto, "User-Agent": "autonomous-agent/" + _version()}
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        if self.secrets.get("token"):
            headers["Authorization"] = "Bearer " + self.secrets["token"]
        data = json.dumps(msg).encode() if msg is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.call_timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self._session = sid
                if resp.status == 202 or msg is None or "id" not in msg:
                    return None
                ctype = resp.headers.get("Content-Type", "")
                raw = resp.read(4 * 1024 * 1024).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise MCPError("auth", f"HTTP {e.code}")
            if e.code == 404 and self._session:
                self._session = None
                raise MCPError("expired", "session expired")
            raise MCPError("http", f"HTTP {e.code}", status=e.code)
        except TimeoutError:
            raise MCPError("timeout", "no answer in time", seconds=int(timeout or self.call_timeout))
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), TimeoutError):
                raise MCPError("timeout", "no answer in time", seconds=int(timeout or self.call_timeout))
            raise MCPError("unreachable", self.scrub(str(e.reason))[:200])
        except OSError as e:
            raise MCPError("unreachable", self.scrub(str(e))[:200])
        if "text/event-stream" in ctype:
            for block in raw.split("\n\n"):
                data_lines = [ln[5:].lstrip() for ln in block.splitlines() if ln.startswith("data:")]
                if not data_lines:
                    continue
                try:
                    obj = json.loads("\n".join(data_lines))
                except ValueError:
                    continue
                if isinstance(obj, dict) and obj.get("id") == msg.get("id") and ("result" in obj or "error" in obj):
                    return obj
            raise MCPError("protocol", "no answer in the event stream")
        try:
            obj = json.loads(raw)
        except ValueError:
            raise MCPError("protocol", "the answer is not JSON")
        if isinstance(obj, list):
            obj = next((o for o in obj if isinstance(o, dict) and o.get("id") == msg.get("id")), {})
        return obj

    # -- JSON-RPC
    def request(self, method: str, params: dict | None = None, timeout: float | None = None) -> dict:
        with self._wlock:
            self._id += 1
            rid = self._id
        msg = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        timeout = timeout or self.call_timeout
        if self.transport == "http":
            resp = self._http(msg, timeout=timeout) or {}
        else:
            q: queue.Queue = queue.Queue()
            self._pending[rid] = q
            try:
                self._write(msg)
                try:
                    resp = q.get(timeout=timeout)
                except queue.Empty:
                    try:
                        self._write({"jsonrpc": "2.0", "method": "notifications/cancelled",
                                     "params": {"requestId": rid, "reason": "timeout"}})
                    except Exception:  # noqa: BLE001
                        pass
                    raise MCPError("timeout", "no answer in time", seconds=int(timeout))
            finally:
                self._pending.pop(rid, None)
            if resp.get("_closed"):
                raise MCPError("crashed", "the program stopped", detail=self.stderr_tail())
        if isinstance(resp.get("error"), dict):
            err = resp["error"]
            raise MCPError("server_error", self.scrub(str(err.get("message") or err))[:300])
        res = resp.get("result")
        return res if isinstance(res, dict) else {}

    def notify(self, method: str, params: dict | None = None) -> None:
        msg = {"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})}
        try:
            if self.transport == "http":
                self._http(msg, timeout=10)
            else:
                self._write(msg)
        except MCPError:
            pass

    def call_tool(self, name: str, arguments: dict) -> str:
        """Plain text of the result (not fenced). Reconnects once if the program stopped / the session expired."""
        for attempt in (0, 1):
            self.connect()
            try:
                res = self.request("tools/call", {"name": name, "arguments": arguments or {}})
                break
            except MCPError as e:
                if attempt == 0 and e.code in ("crashed", "expired"):
                    self.close()
                    continue
                raise
        text = self.scrub(result_text(res))
        if res.get("isError"):
            raise MCPError("tool_error", text[:500])
        return text


def _version() -> str:
    from . import __version__
    return __version__


# ----------------------------------------------------------------------------- registry
_REGISTRIES: "weakref.WeakSet[MCPRegistry]" = weakref.WeakSet()


@atexit.register
def _close_all_at_exit() -> None:
    for r in list(_REGISTRIES):
        try:
            r.close_all()
        except Exception:  # noqa: BLE001
            pass


class MCPRegistry:
    """mcp.json (no secret in it) + tokens / environment values in the SecretStore under "mcp:<id>"."""

    def __init__(self, directory: str | Path, secrets: Any = None, client_factory: Callable[..., MCPClient] | None = None,
                 lang: str = "en"):
        self.path = Path(directory) / "mcp.json"
        self.secrets = secrets
        self.factory = client_factory or MCPClient
        self.lang = lang
        self._lock = threading.RLock()
        self._clients: dict[str, MCPClient] = {}
        self._fail: dict[str, float] = {}
        self.servers: list[dict] = []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for s in data.get("servers") or []:
                if isinstance(s, dict) and s.get("id") and s.get("name"):
                    s.pop("token", None)        # v0.9.6 could keep a token here: never again
                    self.servers.append(s)
        except (OSError, ValueError):
            pass
        _REGISTRIES.add(self)

    # -- storage
    def _save(self) -> None:
        from .userconfig import write_private
        write_private(self.path, {"version": 2, "servers": self.servers})

    def find(self, sid: str) -> dict:
        for s in self.servers:
            if s["id"] == sid:
                return s
        raise KeyError(sid)

    def _secret(self, sid: str) -> dict:
        if self.secrets is None:
            return {}
        raw = self.secrets.get("mcp:" + sid)
        if not raw:
            return {}
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {"token": str(raw)}
        except ValueError:
            return {"token": str(raw)}

    def _set_secret(self, sid: str, value: dict) -> None:
        if self.secrets is None:
            return
        value = {k: v for k, v in value.items() if v}
        if value:
            self.secrets.set("mcp:" + sid, json.dumps(value))
        else:
            try:
                self.secrets.delete("mcp:" + sid)
            except Exception:  # noqa: BLE001
                pass

    def client(self, sid: str) -> MCPClient:
        with self._lock:
            c = self._clients.get(sid)
            if c is None:
                c = self.factory(self.find(sid), self._secret(sid))
                self._clients[sid] = c
            return c

    def _drop_client(self, sid: str) -> None:
        with self._lock:
            c = self._clients.pop(sid, None)
        if c is not None:
            c.close()

    # -- page
    def view(self) -> list[dict]:
        out = []
        for s in self.servers:
            sec = self._secret(s["id"])
            c = self._clients.get(s["id"])
            if not s.get("enabled", True):
                status = "off"
            elif c is not None and c.ready:
                status = "connected"
            elif s.get("error"):
                status = "error"
            elif s.get("tools"):
                status = "ready"          # tested before, starts when the assistant needs it
            else:
                status = "untested"
            from .keys import mask
            out.append({"id": s["id"], "name": s["name"], "transport": s.get("transport"), "preset": s.get("preset"),
                        "where": self._where(s), "enabled": bool(s.get("enabled", True)), "status": status,
                        "error": s.get("error"), "tested": s.get("tested"),
                        "tools": [{k: t.get(k) for k in ("title", "description", "read_only")} for t in s.get("tools") or []],
                        "token_set": bool(sec.get("token")), "token_mask": mask(sec["token"]) if sec.get("token") else None,
                        "env_names": sorted((sec.get("env") or {}).keys())})
        return out

    @staticmethod
    def _where(s: dict) -> str:
        if s.get("transport") == "http":
            u = urllib.parse.urlsplit(str(s.get("url") or ""))
            return f"{u.scheme}://{u.netloc}{u.path}"
        if s.get("preset") == "files" and s.get("folder"):
            home = os.path.expanduser("~")
            f = str(s["folder"])
            return "~" + f[len(home):] if f == home or f.startswith(home + os.sep) else f
        return redact(" ".join(split_command(s.get("command"))))[:200]

    # -- changes (Connect tab, local computer only)
    def save(self, data: dict, sid: str | None = None) -> dict:
        """Add (sid None) or edit a server. data: preset ("files" | "github" | "web" | "custom"), name, folder,
        url, command, token, env ("NAME=value" lines), enabled. A blank token / env keeps the stored one."""
        with self._lock:
            old = self.find(sid) if sid else None
            preset = str(data.get("preset") or (old or {}).get("preset") or "custom")
            if preset not in PRESETS and preset != "custom":
                raise MCPError("bad_config", "unknown preset")
            p = PRESETS.get(preset, {})
            lang = "fr" if str(data.get("lang") or self.lang).startswith("fr") else "en"
            name = str(data.get("name") or "").strip() or (old or {}).get("name") or (p.get("name") or {}).get(lang) or ""
            if not NAME_RE.match(name):
                raise MCPError("bad_name", "give it a short name (40 characters max)")
            if any(s["name"].lower() == name.lower() and s is not old for s in self.servers):
                raise MCPError("duplicate", "a service with this name already exists", name=name)
            s = dict(old) if old else {"id": uuid.uuid4().hex[:10], "enabled": True}
            s.update(name=name, preset=preset, transport=p.get("transport") or data.get("transport") or s.get("transport") or "stdio")
            if preset == "files":
                folder = str(data.get("folder") or s.get("folder") or "").strip() or "~/Documents"
                full = os.path.abspath(os.path.expanduser(folder))
                if not os.path.isdir(full):
                    raise MCPError("no_folder", "this folder does not exist", folder=folder[:120])
                s.update(folder=full, command=list(p["command"]) + [full])
            elif s["transport"] == "http":
                url = str(data.get("url") or p.get("url") or s.get("url") or "").strip()
                u = urllib.parse.urlsplit(url)
                local = (u.hostname or "") in ("127.0.0.1", "localhost", "::1")
                if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or (
                        u.scheme == "http" and not local):
                    raise MCPError("bad_url", "the address must start with https:// (http:// only on this computer)")
                s.update(url=url)
                s.pop("command", None)
            else:
                cmd = data.get("command") if data.get("command") not in (None, "") else s.get("command")
                argv = split_command(cmd)
                if not argv:
                    raise MCPError("bad_command", "type the command that starts the program")
                s.update(command=argv)
                s.pop("url", None)
            if "enabled" in data:
                s["enabled"] = bool(data["enabled"])
            sec = self._secret(s["id"])
            tok = data.get("token")
            if isinstance(tok, str) and tok.strip():
                sec["token"] = tok.strip()
            if data.get("clear_token"):
                sec.pop("token", None)
            env = parse_env(data.get("env"))
            if env:
                sec["env"] = {**(sec.get("env") or {}), **env}
            if preset == "github" and not sec.get("token"):
                raise MCPError("needs_token", "paste your GitHub token")
            s.pop("error", None)
            s.pop("tools", None) if old and (old.get("command") != s.get("command") or old.get("url") != s.get("url")) else None
            self._set_secret(s["id"], sec)
            if old is not None:
                self.servers[self.servers.index(old)] = s
            else:
                self.servers.append(s)
            self._save()
        self._drop_client(s["id"])
        return next(v for v in self.view() if v["id"] == s["id"])

    def set_enabled(self, sid: str, enabled: bool) -> dict:
        with self._lock:
            s = self.find(sid)
            s["enabled"] = bool(enabled)
            self._save()
        if not enabled:
            self._drop_client(sid)
        return next(v for v in self.view() if v["id"] == sid)

    def delete(self, sid: str) -> dict:
        with self._lock:
            s = self.find(sid)
            self.servers.remove(s)
            self._save()
            self._set_secret(sid, {})
        self._drop_client(sid)
        return {"ok": True, "id": sid, "name": s["name"]}

    def test(self, sid: str, timeout: float | None = None) -> dict:
        """Start (or restart) the server, list what it can do, remember it. Never raises for server problems."""
        self._drop_client(sid)
        s = self.find(sid)
        c = self.client(sid)
        if timeout:
            c.connect_timeout = timeout
        try:
            tools = c.connect()
            self._remember(sid, tools)
        except MCPError as e:
            self._remember_error(sid, e)
        return next(v for v in self.view() if v["id"] == s["id"])

    def _remember(self, sid: str, tools: list[dict]) -> None:
        with self._lock:
            s = self.find(sid)
            s["tools"] = [ct for ct in (compact_tool(t) for t in tools)
                          if ct and "deprecated" not in (ct["title"] + ct["description"][:40]).lower()]
            s.pop("error", None)
            s["tested"] = time.strftime("%Y-%m-%d %H:%M")
            self._fail.pop(sid, None)
            self._save()

    def _remember_error(self, sid: str, e: MCPError) -> None:
        with self._lock:
            try:
                s = self.find(sid)
            except KeyError:
                return
            s["error"] = {"code": e.code, "params": {k: str(v)[:300] for k, v in e.params.items()},
                          "message": redact(str(e))[:300]}
            s["tested"] = time.strftime("%Y-%m-%d %H:%M")
            self._fail[sid] = time.time()
            self._save()

    # -- agents
    def enabled(self) -> list[dict]:
        return [s for s in self.servers if s.get("enabled", True)]

    def agent_tools(self, connect_timeout: float = 20.0) -> list[Tool]:
        """Tools of the enabled services. Known tools come from the cache (no start); a never-tested
        service is tried once, quickly; a service that just failed is skipped (the page shows why)."""
        out: list[Tool] = []
        for s in self.enabled():
            sid = s["id"]
            if not s.get("tools"):
                if time.time() - self._fail.get(sid, 0) < RETRY_AFTER_FAIL:
                    continue
                c = self.client(sid)
                c.connect_timeout = min(c.connect_timeout, connect_timeout)
                try:
                    self._remember(sid, c.connect())
                except MCPError as e:
                    self._remember_error(sid, e)
                    continue
            out += make_tools(self, self.find(sid))
        return out

    def close_all(self) -> None:
        with self._lock:
            ids = list(self._clients)
        for sid in ids:
            self._drop_client(sid)


def parse_env(text: Any) -> dict:
    """'NAME=value' lines (or a dict) -> {NAME: value}. Values are secrets (stored like keys)."""
    out = {}
    if isinstance(text, dict):
        items = text.items()
    else:
        items = [ln.split("=", 1) for ln in str(text or "").splitlines() if "=" in ln]
    for k, v in items:
        k, v = str(k).strip(), str(v).strip()
        if not ENV_NAME_RE.match(k):
            raise MCPError("bad_env", "one line per value: NAME=value", name=k[:40])
        if v:
            out[k] = v
    return out


def make_tools(registry: MCPRegistry, server: dict) -> list[Tool]:
    """Agent tools for one service, from its cached tool list. The program starts on the first call."""
    sid, service = server["id"], server["name"]
    prefix = f"mcp_{slug(service)}_"
    tools, seen = [], set()
    for t in server.get("tools") or []:
        tname = (prefix + TOOL_NAME_RE.sub("_", t["name"]))[:64]
        if tname in seen:
            continue
        seen.add(tname)
        LABELS[tname] = (service, t.get("title") or t["name"])

        def run(ctx: ToolContext, args: dict, _real=t["name"], _sid=sid, _service=service) -> str:
            try:
                c = registry.client(_sid)
                text = c.call_tool(_real, args)
            except KeyError:
                raise ToolError(f"The service “{_service}” was removed in the Connect tab.")
            except MCPError as e:
                if e.code not in ("tool_error", "server_error"):
                    registry._remember_error(_sid, e)
                raise ToolError(plain_error(_service, e))
            return fence(_service, text)

        tools.append(Tool(name=tname, description=f"[{service}] {t.get('description') or t.get('title')}",
                          category="read" if t.get("read_only") else "network",
                          parameters=t.get("schema") or {"type": "object", "properties": {}}, func=run,
                          service=service, title=t.get("title")))
    return tools


def plain_error(service: str, e: MCPError) -> str:
    why = {"needs_program": f"{e.params.get('program', 'a program')} is not installed on this computer",
           "not_found": "its program was not found", "timeout": "it did not answer in time",
           "auth": "it refused the token (expired or missing rights)", "unreachable": "it cannot be reached",
           "crashed": "its program stopped", "tool_error": f"it answered with an error: {e}",
           "server_error": f"it answered with an error: {e}"}.get(e.code, str(e))
    return (f"The connected service “{service}” could not do this: {redact(why)}. Tell the user in one simple "
            f"sentence; they can check it with the Test button in the Connect tab. Do not retry more than once.")


def service_of(tool_name: str) -> tuple[str, str] | None:
    return LABELS.get(tool_name)


# French request words -> the English words servers use in tool names (cheap relevance, no model call)
SYNONYMS = {"lis": "read", "lire": "read", "lit": "read", "ouvr": "read", "fichier": "file", "dossier": "directory",
            "répertoire": "directory", "list": "list", "cherch": "search", "recherch": "search", "trouv": "search",
            "écri": "write", "ecri": "write", "enregistr": "write", "cré": "create", "cre": "create", "modifi": "edit",
            "change": "edit", "déplac": "move", "renomm": "move", "copi": "copy", "ticket": "issue", "dépôt": "repository",
            "depot": "repository", "branche": "branch", "commentair": "comment", "info": "info", "taille": "size",
            "arbo": "tree", "note": "note", "agenda": "calendar", "événement": "event", "evenement": "event",
            "mail": "email", "courriel": "email", "envoi": "send", "envoy": "send"}


def pick_tools(schemas: list[dict], text: str, limit: int = MAX_TOOLS_SENT, used: set | None = None) -> list[dict]:
    """Keep at most `limit` MCP tool schemas: the ones already used in this conversation first, then the
    ones whose name / description share the most words with the request. Other schemas are untouched."""
    mcp_s = [s for s in schemas if str((s.get("function") or {}).get("name", "")).startswith("mcp_")]
    if len(mcp_s) <= limit:
        return schemas
    words = set(re.findall(r"[a-zà-ÿ0-9]{3,}", str(text or "").lower()))
    words |= {en for w in words for fr, en in SYNONYMS.items() if w.startswith(fr)}
    used = used or set()

    def score(i_s: tuple[int, dict]) -> tuple:
        i, s = i_s
        f = s.get("function") or {}
        name = f.get("name", "")
        hay = set(re.findall(r"[a-zà-ÿ0-9]{3,}", (name.replace("_", " ") + " " + f.get("description", "")).lower()))
        svc = (LABELS.get(name) or ("", ""))[0].lower()
        ro = f.get("description", "").startswith("[read]")
        return (name in used, len(words & hay) + (2 if svc and svc in str(text).lower() else 0), ro, -i)
    keep = {id(s) for _, s in sorted(enumerate(mcp_s), key=score, reverse=True)[:limit]}
    return [s for s in schemas if not str((s.get("function") or {}).get("name", "")).startswith("mcp_") or id(s) in keep]


def preset_view() -> list[dict]:
    """The ready-made services for the page, with what each one needs and whether this computer has it."""
    out = []
    for pid, p in PRESETS.items():
        rt = p.get("runtime")
        out.append({"id": pid, "name": p["name"], "needs": p.get("needs"), "token_link": p.get("token_link"),
                    "program": PROGRAM_NAMES.get(rt) if rt else None, "link": INSTALL_LINKS.get(rt) if rt else None,
                    "installed": (find_program("npx") is not None and find_program("node") is not None)
                    if rt == "node" else True,
                    "default_folder": "~/Documents" if p.get("needs") == "folder" else None})
    return out
