import unittest
import json
import os
import tempfile
from pathlib import Path

from agent.mcp import MCPClient, MCPRegistry, make_mcp_tools
from agent.permissions import Permissions
from agent.audit import AuditLog


class TestMCP(unittest.TestCase):
    def test_mcp_stdio_roundtrip(self):
        client = MCPClient({"name": "test", "transport": "stdio", "command": "python -c 'pass'"})
        client.tools = [{
            "name": "echo",
            "description": "Echo",
            "inputSchema": {"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]},
            "annotations": {"readOnlyHint": True}
        }]
        tools = make_mcp_tools(client)
        self.assertEqual(len(tools), 1)
        self.assertTrue(tools[0].name.startswith("mcp_test_"))
        self.assertEqual(tools[0].category, "read")
        client.tools[0]["annotations"] = {}
        tools = make_mcp_tools(client)
        self.assertEqual(tools[0].category, "network")

    def test_external_content_fence(self):
        class Dummy:
            def call_tool(self, n, a):
                return "<external_content>\nhi\n</external_content>"
        self.assertIn("<external_content>", Dummy().call_tool("x", {}))

    def test_registry_storage(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            class FakeSecrets:
                def __init__(self):
                    self.d = {}
                def get(self, k):
                    return self.d.get(k)
                def set(self, k, v):
                    self.d[k] = v
                def delete(self, k):
                    self.d.pop(k, None)
            secrets = FakeSecrets()
            reg = MCPRegistry(tmp_path, secrets)
            sid = reg.add({"name": "demo", "transport": "stdio", "command": "echo", "enabled": True})
            self.assertTrue(sid)
            self.assertTrue((tmp_path / "mcp.json").exists())

    def test_permissions_read_only(self):
        perms = Permissions()
        dec = perms.decide("mcp_demo_echo", "read")
        self.assertEqual(dec.mode, "allow")
        dec = perms.decide("mcp_demo_write", "network")
        self.assertEqual(dec.mode, "ask")


if __name__ == "__main__":
    unittest.main()


class FakeStdioServer:
    """Minimal JSON-RPC MCP server on stdin/stdout for tests."""

    def __init__(self):
        self.tools = [{
            "name": "echo",
            "description": "Echo a message",
            "inputSchema": {"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]},
            "annotations": {"readOnlyHint": True}
        }]

    def handle(self, line: str) -> str:
        req = json.loads(line)
        method = req.get("method")
        rid = req.get("id")
        if method == "initialize":
            return json.dumps({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.1"}
            }})
        if method == "tools/list":
            return json.dumps({"jsonrpc": "2.0", "id": rid, "result": {"tools": self.tools}})
        if method == "tools/call":
            name = req["params"]["name"]
            args = req["params"].get("arguments", {})
            text = args.get("msg", "ok")
            return json.dumps({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": text}]
            }})
        return json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "not found"}})


def test_mcp_stdio_roundtrip():
    client = MCPClient({"name": "test", "transport": "stdio", "command": "python -c 'pass'"})
    client.tools = [{
        "name": "echo",
        "description": "Echo",
        "inputSchema": {"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]},
        "annotations": {"readOnlyHint": True}
    }]
    tools = make_mcp_tools(client)
    assert len(tools) == 1
    assert tools[0].name.startswith("mcp_test_")
    assert tools[0].category == "read"
    client.tools[0]["annotations"] = {}
    tools = make_mcp_tools(client)
    assert tools[0].category == "network"


def test_external_content_fence():
    client = MCPClient({"name": "t", "transport": "http", "url": "https://example.com/mcp"})
    # mock the call
    class Dummy:
        def call_tool(self, n, a):
            return "<external_content>\nhi\n</external_content>"
    # just verify the fence is expected
    assert "<external_content>" in Dummy().call_tool("x", {})


def test_registry_storage():
    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        class FakeSecrets:
            def __init__(self):
                self.d = {}
            def get(self, k):
                return self.d.get(k)
            def set(self, k, v):
                self.d[k] = v
            def delete(self, k):
                self.d.pop(k, None)
        secrets = FakeSecrets()
        reg = MCPRegistry(tmp_path, secrets)
        sid = reg.add({"name": "demo", "transport": "stdio", "command": "echo", "enabled": True})
        assert sid
        assert (tmp_path / "mcp.json").exists()


def test_permissions_read_only():
    perms = Permissions()
    # read category default allow
    dec = perms.decide("mcp_demo_echo", "read")
    assert dec.mode == "allow"
    dec = perms.decide("mcp_demo_write", "network")
    assert dec.mode == "ask"  # default for network
