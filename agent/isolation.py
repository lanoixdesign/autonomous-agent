"""Isolated workspace copies for parallel sub-agents, and the merge back into the parent workspace.

copy:  the parent workspace is copied into a private temp dir (mkdtemp, mode 0700). Ignored: VCS and
       virtualenv/cache/build dirs (IGNORE_DIRS), symlinks, files larger than max_file_bytes. If the
       whole copy would exceed max_total_bytes, `WorkspaceTooLarge` is raised (the caller then falls
       back to sequential children in the shared workspace).
merge: for every file a child created, modified or deleted (compared with the snapshot taken before
       the batch started):
         - changed by exactly one child, and unchanged in the parent meanwhile -> applied;
         - several children produced the same content -> applied once;
         - otherwise (several children differ, or the parent changed it meanwhile) -> CONFLICT: the
           parent file is NOT touched; each child's version is written next to it as
           `<file>.conflict-<agent id>` (a deletion is only reported).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

IGNORE_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "env", ".env", "node_modules", "__pycache__",
               ".agent", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox", "dist", "build",
               ".idea", ".cache"}
DELETED = None


class WorkspaceTooLarge(Exception):
    pass


@dataclass
class Limits:
    max_total_bytes: int = 200 * 1024 * 1024
    max_file_bytes: int = 20 * 1024 * 1024


def _hash(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(root: Path, limits: Limits | None = None) -> dict[str, str]:
    """{relative posix path: sha256} for the files that take part in copy/merge."""
    limits = limits or Limits()
    root = Path(root)
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in IGNORE_DIRS and not d.endswith(".egg-info")
                             and not os.path.islink(os.path.join(dirpath, d)))
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.is_symlink() or not p.is_file():
                continue
            try:
                if p.stat().st_size > limits.max_file_bytes:
                    continue
                out[p.relative_to(root).as_posix()] = _hash(p)
            except OSError:
                continue
    return out


def make_copy(src: Path, files: dict[str, str], limits: Limits | None = None, prefix: str = "agent-") -> Path:
    """Copy `files` (from `scan`) of `src` into a new private temp dir; returns its path."""
    limits = limits or Limits()
    total = sum((Path(src) / rel).stat().st_size for rel in files)
    if total > limits.max_total_bytes:
        raise WorkspaceTooLarge(f"workspace is {total // (1024 * 1024)} MB, over the "
                                f"{limits.max_total_bytes // (1024 * 1024)} MB copy limit")
    dst = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        for rel in files:
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(src) / rel, target)
    except BaseException:
        shutil.rmtree(dst, ignore_errors=True)
        raise
    return dst


def changes(base: dict[str, str], copy_root: Path, limits: Limits | None = None) -> dict[str, str | None]:
    """{path: new sha256, or None if deleted} for what a child changed in its copy."""
    now = scan(copy_root, limits)
    out: dict[str, str | None] = {rel: h for rel, h in now.items() if base.get(rel) != h}
    out.update({rel: DELETED for rel in base if rel not in now})
    return out


@dataclass
class MergeReport:
    applied: list[dict] = field(default_factory=list)     # {"path", "agent", "action"}
    conflicts: list[dict] = field(default_factory=list)   # {"path", "agents", "reason", "files"}

    def text(self) -> str:
        if not self.applied and not self.conflicts:
            return "[merge] no file changes from the sub-agents"
        lines = []
        if self.applied:
            lines.append("[merge] applied: " + ", ".join(f"{a['path']} ({a['action']} by {a['agent']})"
                                                          for a in self.applied))
        for c in self.conflicts:
            kept = f"; their versions: {', '.join(c['files'])}" if c["files"] else ""
            lines.append(f"[merge] CONFLICT {c['path']} ({c['reason']}; agents {', '.join(c['agents'])})"
                         f": parent file left untouched{kept}")
        return "\n".join(lines)


def _safe_target(root: Path, rel: str) -> bool:
    """Never write through a symlink, nor outside the parent workspace."""
    root = root.resolve()
    p = root
    for part in Path(rel).parts:
        p = p / part
        if p.is_symlink():
            return False
    return (root / rel).resolve().is_relative_to(root) if hasattr(Path, "is_relative_to") else True


def merge(parent_root: Path, base: dict[str, str], children: list[tuple[str, Path]],
          limits: Limits | None = None) -> MergeReport:
    """Merge the children's copies (agent id, copy path) back into `parent_root`."""
    parent_root = Path(parent_root)
    per_path: dict[str, list[tuple[str, str | None]]] = {}
    for agent_id, root in children:
        for rel, h in changes(base, root, limits).items():
            per_path.setdefault(rel, []).append((agent_id, h))
    current = scan(parent_root, limits)
    report = MergeReport()
    for rel in sorted(per_path):
        edits = per_path[rel]
        agents = [a for a, _ in edits]
        parent_changed = current.get(rel) != base.get(rel)
        if not _safe_target(parent_root, rel):
            report.conflicts.append({"path": rel, "agents": agents, "files": [],
                                     "reason": "symlink or path outside the workspace in the parent"})
            continue
        results = {h for _, h in edits}
        if not parent_changed and len(results) == 1:
            agent_id, h = edits[0]
            src = dict(children)[agent_id] / rel
            dst = parent_root / rel
            if h is DELETED:
                if dst.is_file():
                    dst.unlink()
                action = "deleted"
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                action = "modified" if rel in base else "created"
            report.applied.append({"path": rel, "agent": "+".join(agents), "action": action})
            continue
        written = []
        for agent_id, h in edits:
            if h is DELETED:
                continue
            target = parent_root / f"{rel}.conflict-{agent_id}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dict(children)[agent_id] / rel, target)
            written.append(target.relative_to(parent_root).as_posix())
        reason = "changed in the parent meanwhile" if parent_changed else "changed differently by several sub-agents"
        report.conflicts.append({"path": rel, "agents": agents, "reason": reason, "files": written})
    return report
