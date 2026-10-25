"""File tools confined to the workspace (symlinks resolved; no escaping with ../)."""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from . import Tool, ToolContext, ToolError, params, s


def resolve(ctx: ToolContext, rel: str) -> Path:
    root = ctx.workspace.resolve()
    p = (root / (rel or ".")).resolve()
    if p != root and root not in p.parents:
        raise ToolError(f"path escapes the workspace: {rel}")
    return p


def _read(ctx: ToolContext, a: dict) -> str:
    p = resolve(ctx, a["path"])
    if not p.is_file():
        raise ToolError(f"not a file: {a['path']}")
    data = p.read_text(encoding="utf-8", errors="replace")
    start = int(a.get("offset") or 1)
    lines = data.splitlines()
    limit = int(a.get("limit") or 400)
    chunk = lines[start - 1:start - 1 + limit]
    out = "\n".join(f"{i:5d}| {ln}" for i, ln in enumerate(chunk, start))
    if start - 1 + limit < len(lines):
        out += f"\n... ({len(lines)} lines total, use offset to continue)"
    return out[:ctx.max_output] or "(empty file)"


def _list(ctx: ToolContext, a: dict) -> str:
    p = resolve(ctx, a.get("path") or ".")
    if not p.is_dir():
        raise ToolError(f"not a directory: {a.get('path')}")
    root = ctx.workspace.resolve()
    out = []
    for dirpath, dirnames, filenames in os.walk(p):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".venv"))
        depth = Path(dirpath).relative_to(p).parts
        if len(depth) >= int(a.get("depth") or 2):
            dirnames[:] = []
        for f in sorted(filenames):
            out.append(str((Path(dirpath) / f).relative_to(root)))
        if len(out) > 500:
            out.append("... (truncated)")
            break
    return "\n".join(out) or "(empty)"


def _search(ctx: ToolContext, a: dict) -> str:
    needle = a["query"].lower()
    glob = a.get("glob") or "*"
    root = ctx.workspace.resolve()
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
        for f in filenames:
            if not fnmatch.fnmatch(f, glob):
                continue
            fp = Path(dirpath) / f
            try:
                for i, line in enumerate(fp.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if needle in line.lower():
                        hits.append(f"{fp.relative_to(root)}:{i}: {line.strip()[:200]}")
                        if len(hits) >= 100:
                            return "\n".join(hits) + "\n... (truncated)"
            except OSError:
                continue
    return "\n".join(hits) or "no match"


def _write(ctx: ToolContext, a: dict) -> str:
    p = resolve(ctx, a["path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(a.get("content", ""), encoding="utf-8")
    return f"wrote {len(a.get('content', ''))} chars to {a['path']}"


def _edit(ctx: ToolContext, a: dict) -> str:
    p = resolve(ctx, a["path"])
    if not p.is_file():
        raise ToolError(f"not a file: {a['path']}")
    text = p.read_text(encoding="utf-8")
    old, new = a["old"], a.get("new", "")
    n = text.count(old)
    if n == 0:
        raise ToolError("`old` text not found; read the file first and copy it exactly")
    if n > 1 and not a.get("replace_all"):
        raise ToolError(f"`old` text found {n} times; add more context or set replace_all=true")
    text = text.replace(old, new) if a.get("replace_all") else text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")
    return f"edited {a['path']} ({n if a.get('replace_all') else 1} replacement(s))"


TOOLS = [
    Tool("read_file", "Read a text file in the workspace (with line numbers).", "read",
         params(["path"], path=s("path relative to the workspace"),
                offset={"type": "integer", "description": "first line (1-based)"},
                limit={"type": "integer", "description": "max lines"}),
         _read, "path", "path"),
    Tool("list_files", "List files under a workspace directory.", "read",
         params([], path=s("directory, default '.'"), depth={"type": "integer"}), _list, "path", "path"),
    Tool("search_files", "Case-insensitive text search in workspace files.", "read",
         params(["query"], query=s("text to find"), glob=s("file name glob, e.g. *.py")), _search),
    Tool("write_file", "Create or overwrite a file in the workspace.", "write",
         params(["path", "content"], path=s("path"), content=s("full file content")), _write, "path", "path"),
    Tool("edit_file", "Replace an exact text fragment in a workspace file.", "write",
         params(["path", "old", "new"], path=s("path"), old=s("exact existing text"), new=s("replacement"),
                replace_all={"type": "boolean"}), _edit, "path", "path"),
]
