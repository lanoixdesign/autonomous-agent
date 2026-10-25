import os
import subprocess

import pytest

from agent.tools import ToolError, default_registry
from agent.tools.web import html_to_text

REG = default_registry()


def run(ctx, tool_name, **args):
    return REG.get(tool_name).func(ctx, args)


def test_every_tool_has_a_category():
    cats = {t.category for t in REG.tools.values()}
    assert cats <= {"read", "write", "execute", "network", "send", "spend"}
    assert REG.get("github_write").category == "send"
    assert REG.get("shell").category == "execute"
    assert REG.get("web_fetch").category == "network"


def test_read_write_edit_list_search(ctx):
    assert "hello world" in run(ctx, "read_file", path="hello.txt")
    run(ctx, "write_file", path="sub/new.txt", content="alpha beta\n")
    assert (ctx.workspace / "sub/new.txt").read_text() == "alpha beta\n"
    run(ctx, "edit_file", path="sub/new.txt", old="beta", new="gamma")
    assert (ctx.workspace / "sub/new.txt").read_text() == "alpha gamma\n"
    assert "sub/new.txt" in run(ctx, "list_files", path=".")
    assert "hello.txt:1" in run(ctx, "search_files", query="HELLO")


def test_edit_requires_unique_match(ctx):
    (ctx.workspace / "d.txt").write_text("x x")
    with pytest.raises(ToolError):
        run(ctx, "edit_file", path="d.txt", old="x", new="y")
    run(ctx, "edit_file", path="d.txt", old="x", new="y", replace_all=True)
    assert (ctx.workspace / "d.txt").read_text() == "y y"


def test_workspace_escape_blocked(ctx, tmp_path):
    (tmp_path / "outside.txt").write_text("nope")
    with pytest.raises(ToolError):
        run(ctx, "read_file", path="../outside.txt")
    os.symlink(tmp_path / "outside.txt", ctx.workspace / "link.txt")
    with pytest.raises(ToolError):
        run(ctx, "read_file", path="link.txt")


def test_shell_runs_in_workspace_without_secrets(ctx, monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "supersecretvalue123")
    out = run(ctx, "shell", command="pwd; env")
    assert out.startswith("exit=0")
    assert str(ctx.workspace.resolve()) in out
    assert "supersecretvalue123" not in out and "MY_API_KEY" not in out


def test_shell_timeout(ctx):
    with pytest.raises(ToolError):
        run(ctx, "shell", command="sleep 5", timeout=1)


def test_memory_and_skill_tools(ctx):
    assert "saved" in run(ctx, "memory_write", text="The project uses pytest", tags=["tests"])
    assert "pytest" in run(ctx, "memory_recall", query="pytest")
    assert "forgot 1" in run(ctx, "memory_forget", query="pytest")
    assert "research" in run(ctx, "list_skills")
    assert "Code review" in run(ctx, "load_skill", name="code-review")
    with pytest.raises(ToolError):
        run(ctx, "load_skill", name="nope")


def test_web_fetch_rejects_non_http(ctx):
    with pytest.raises(ToolError):
        run(ctx, "web_fetch", url="file:///etc/passwd")


def test_html_to_text():
    assert html_to_text("<p>Hi&amp;<script>x()</script><b>there</b></p>") == "Hi& there"


def test_github_path_validation(ctx, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x" * 20)
    with pytest.raises(ToolError):
        run(ctx, "github_get", path="https://evil.example/")
    with pytest.raises(ToolError):
        run(ctx, "github_write", path="/repos/o/r/issues", method="GET")
