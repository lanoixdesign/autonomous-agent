"""GitHub tools. Uses GITHUB_TOKEN / GH_TOKEN with the REST API, or falls back to the `gh` CLI.

github_get is a read over the network (category `network`); github_write changes things on
GitHub on your behalf (category `send`, so it is never auto-approved by --yolo).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

from .. import USER_AGENT
from . import Tool, ToolContext, ToolError, params, s

API = "https://api.github.com"


def _token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def request(method: str, path: str, body: dict | None = None) -> str:
    path = "/" + path.lstrip("/")
    if not path.startswith(("/repos", "/user", "/users", "/orgs", "/search", "/gists", "/issues", "/notifications", "/rate_limit")):
        raise ToolError("path must be a GitHub REST path like /repos/OWNER/REPO/issues")
    tok = _token()
    if tok:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(API + path, data=data, method=method, headers={
            "Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": USER_AGENT,
            **({"Content-Type": "application/json"} if data else {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            raise ToolError(f"GitHub HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")
        except urllib.error.URLError as e:
            raise ToolError(f"GitHub unreachable: {e}")
    if shutil.which("gh"):
        cmd = ["gh", "api", "-X", method, path]
        inp = None
        if body is not None:
            cmd += ["--input", "-"]
            inp = json.dumps(body)
        r = subprocess.run(cmd, capture_output=True, text=True, input=inp, timeout=60)
        if r.returncode != 0:
            raise ToolError(f"gh api failed: {r.stderr.strip()[:500]}")
        return r.stdout
    raise ToolError("no GitHub credentials: set GITHUB_TOKEN or log in with `gh auth login`")


def _short(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + "\n... (truncated)"


def _get(ctx: ToolContext, a: dict) -> str:
    return _short(request("GET", a["path"]), ctx.max_output)


def _write(ctx: ToolContext, a: dict) -> str:
    method = a.get("method", "POST").upper()
    if method not in ("POST", "PATCH", "PUT", "DELETE"):
        raise ToolError("method must be POST, PATCH, PUT or DELETE")
    body = a.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body) if body.strip() else None
        except json.JSONDecodeError as e:
            raise ToolError(f"body is not valid JSON: {e}")
    return _short(request(method, a["path"], body), ctx.max_output)


TOOLS = [
    Tool("github_get", "GET a GitHub REST path, e.g. /repos/OWNER/REPO/pulls?state=open.", "network",
         params(["path"], path=s("REST path")), _get, "url", lambda a: API + "/" + str(a.get("path", "")).lstrip("/")),
    Tool("github_write", "POST/PATCH/PUT/DELETE on a GitHub REST path (issues, comments, PRs...).", "send",
         params(["path"], path=s("REST path"), method=s("POST|PATCH|PUT|DELETE"),
                body={"type": "object", "description": "JSON body"}),
         _write, "url", lambda a: API + "/" + str(a.get("path", "")).lstrip("/")),
]
