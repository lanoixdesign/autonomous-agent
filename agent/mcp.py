"""MCP (Model Context Protocol) client in pure Python (stdlib only).

Supports stdio (launch a local process) and HTTP streamable transports.
JSON-RPC 2.0: initialize, tools/list, tools/call.
Results are fenced in <external_content>. Read-only tools (readOnlyHint) follow read rules;
others require user agreement. Secrets stored like API keys (0600, masked).
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

from .tools import Tool, ToolContext, ToolError, params, s
from .netguard import check_url, BlockedURL
from .redact import redact
from .audit import AuditLog

PROTOCOL_VERSION = "2025-03-26"
TIMEOUT = 30.0
MAX_OUTPUT = 12000


class MCPError(Exception):
    pass


class MCPClient:
    """One connection to an MCP server (stdio or HTTP)."""

    def __init__(self, config: dict, secrets: Any = None, audit: AuditLog | None = None):
        self.config = config
        self.secrets = secrets
        self.audit = audit
        self.name = config.get("name", "mcp")
        self.transport = config.get("transport", "stdio")  # stdio | http
        self.command = config.get("command")
        self.url = config.get("url")
        self.env = config.get("env") or {}
        self.token = config.get("token")
        self.enabled = config.get("enabled", True)
        self._proc: subprocess.Popen | None = None
        self._id = 0
        self._lock = threading.Lock()
        self.tools: list[dict] = []
        self.initialized = False

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _env(self) -> dict:
        e = os.environ.copy()
        e.update(self.env)
        if self.token and self.secrets:
            tok = self.secrets.get(f"mcp:{self.config.get('id')}")
            if tok:
                e["MCP_TOKEN"] = tok
        return e

    def start(self) -> None:
        if self.transport == "stdio":
            if not self.command:
                raise MCPError("stdio requires a command")
            self._proc = subprocess.Popen(
                self.command if isinstance(self.command, list) else self.command.split(),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=self._env(), text=True, bufsize=1
            )
        self.initialized = False

    def close(self) -> None:
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                self._proc.kill()
            self._proc = None

    def _rpc_stdio(self, method: str, params: dict | None = None) -> dict:
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            raise MCPError("stdio process not running")
        req = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params is not None:
            req["params"] = params
        line = json.dumps(req) + "\n"
        self._proc.stdin.write(line)
        self._proc.stdin.flush()
        # simple read one line (for tests; production should handle multi-line)
        resp_line = self._proc.stdout.readline()
        if not resp_line:
            raise MCPError("stdio EOF")
        return json.loads(resp_line)

    def _rpc_http(self, method: str, params: dict | None = None) -> dict:
        if not self.url:
            raise MCPError("http requires a url")
        try:
            check_url(self.url)
        except BlockedURL as e:
            raise MCPError(str(e))
        req = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params is not None:
            req["params"] = params
        data = json.dumps(req).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.token and self.secrets:
            tok = self.secrets.get(f"mcp:{self.config.get('id')}")
            if tok:
                headers["Authorization"] = f"Bearer {tok}"
        r = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(r, timeout=TIMEOUT) as resp:
                body = resp.read().decode()
                # basic SSE or plain JSON
                if "data:" in body:
                    for line in body.splitlines():
                        if line.startswith("data:"):
                            return json.loads(line[5:].strip())
                return json.loads(body)
        except urllib.error.URLError as e:
            raise MCPError(f"HTTP error: {e}")

    def rpc(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            if self.transport == "stdio":
                return self._rpc_stdio(method, params)
            return self._rpc_http(method, params)

    def initialize(self) -> dict:
        params = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "autonomous-agent", "version": "0.9.6"}
        }
        res = self.rpc("initialize", params)
        self.initialized = True
        # send initialized notification
        try:
            self.rpc("notifications/initialized")
        except Exception:
            pass
        return res.get("result", {})

    def list_tools(self) -> list[dict]:
        if not self.initialized:
            self.initialize()
        res = self.rpc("tools/list")
        self.tools = res.get("result", {}).get("tools", [])
        return self.tools

    def call_tool(self, name: str, arguments: dict) -> str:
        res = self.rpc("tools/call", {"name": name, "arguments": arguments})
        result = res.get("result", {})
        content = result.get("content", [])
        texts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                texts.append(c.get("text", ""))
        text = "\n".join(texts) or json.dumps(result)
        return f"<external_content>\n{text[:MAX_OUTPUT]}\n</external_content>"


def make_mcp_tools(client: MCPClient) -> list[Tool]:
    """Convert MCP tools to agent Tools with mcp_<server>_<tool> prefix."""
    tools = []
    server = client.name.replace(" ", "_").lower()
    for t in client.tools:
        name = f"mcp_{server}_{t['name']}"
        desc = t.get("description", t["name"])
        schema = t.get("inputSchema", {"type": "object", "properties": {}})
        # map to our params format (simplified)
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        annotations = t.get("annotations") or {}
        read_only = annotations.get("readOnlyHint", False)
        category = "read" if read_only else "network"  # default; permissions will ask for non-read

        def _func(ctx: ToolContext, args: dict, _client=client, _name=t["name"]) -> str:
            if not _client.initialized:
                _client.start()
                _client.initialize()
                _client.list_tools()
            try:
                out = _client.call_tool(_name, args)
                if _client.audit:
                    _client.audit.record(tool=name, args=redact(args), result_preview=out[:200])
                return out
            except Exception as e:
                raise ToolError(str(e))

        tool = Tool(
            name=name,
            description=desc,
            category=category,
            parameters={"type": "object", "properties": properties, "required": required},
            func=_func,
        )
        tools.append(tool)
    return tools


class MCPRegistry:
    """Manages user-added MCP servers (stored in mcp.json + secrets)."""

    def __init__(self, directory: str | Path, secrets: Any, audit: AuditLog | None = None):
        self.path = Path(directory) / "mcp.json"
        self.secrets = secrets
        self.audit = audit
        self.clients: dict[str, MCPClient] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for cfg in data.get("servers", []):
                if cfg.get("enabled", True):
                    c = MCPClient(cfg, self.secrets, self.audit)
                    self.clients[cfg["id"]] = c
        except (OSError, ValueError):
            pass

    def _save(self, servers: list[dict]) -> None:
        from .userconfig import write_private
        write_private(self.path, {"version": 1, "servers": servers})

    def list_servers(self) -> list[dict]:
        return [{"id": c.config.get("id"), "name": c.name, "transport": c.transport,
                 "enabled": c.enabled, "tools": len(c.tools)} for c in self.clients.values()]

    def add(self, cfg: dict) -> str:
        sid = cfg.get("id") or str(uuid.uuid4())[:8]
        cfg["id"] = sid
        if "token" in cfg and self.secrets:
            self.secrets.set(f"mcp:{sid}", cfg.pop("token"))
        servers = [c.config for c in self.clients.values()]
        servers.append(cfg)
        self._save(servers)
        if cfg.get("enabled", True):
            c = MCPClient(cfg, self.secrets, self.audit)
            self.clients[sid] = c
        return sid

    def remove(self, sid: str) -> None:
        if sid in self.clients:
            self.clients[sid].close()
            del self.clients[sid]
        # rewrite file
        servers = [c.config for c in self.clients.values()]
        self._save(servers)
        if self.secrets:
            self.secrets.delete(f"mcp:{sid}")

    def get_tools(self) -> list[Tool]:
        all_tools = []
        for c in self.clients.values():
            if c.enabled:
                try:
                    if not c.tools:
                        c.start()
                        c.list_tools()
                    all_tools.extend(make_mcp_tools(c))
                except Exception:
                    continue
        return all_tools
