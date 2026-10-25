"""Shell tool. Runs in the workspace with a timeout and an environment scrubbed of secrets."""
from __future__ import annotations

import subprocess

from ..redact import scrubbed_env
from . import Tool, ToolContext, ToolError, params, s


def _shell(ctx: ToolContext, a: dict) -> str:
    cmd = a["command"]
    timeout = min(int(a.get("timeout") or ctx.shell_timeout), 600)
    try:
        r = subprocess.run(cmd, shell=True, cwd=ctx.workspace, capture_output=True, text=True,
                           timeout=timeout, env=scrubbed_env(), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise ToolError(f"timeout after {timeout}s")
    out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
    if len(out) > ctx.max_output:
        out = out[:ctx.max_output] + f"\n... ({len(out) - ctx.max_output} chars truncated)"
    return f"exit={r.returncode}\n{out}".rstrip()


TOOLS = [
    Tool("shell", "Run a shell command in the workspace (bash/sh). Secret env vars are removed.", "execute",
         params(["command"], command=s("command line"), timeout={"type": "integer", "description": "seconds"}),
         _shell, "command", "command"),
]
