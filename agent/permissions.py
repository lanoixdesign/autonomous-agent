"""Permission model: per category and per tool, modes allow / ask / deny, plus patterns.

Resolution order for one tool call:
  1. mode = tools[<tool>] if set, else defaults[<category>]
  2. deny patterns (paths / commands / domains) matching the subject  -> deny (always wins)
  3. paths.allow non-empty and subject path not matching             -> deny
  4. commands.allow / domains.allow matching and mode == ask        -> allow
  5. --yolo: ask -> allow, EXCEPT for categories send and spend (those keep the
     mode written in the file; set them to allow yourself if you really want it)
"""
from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MODES = ("allow", "ask", "deny")
CATEGORIES = ("read", "write", "execute", "network", "send", "spend")
SAFE_DEFAULTS = {
    "read": "allow",
    "write": "ask",
    "execute": "ask",
    "network": "ask",
    "send": "ask",
    "spend": "deny",
}
YOLO_PROTECTED = ("send", "spend")

DEFAULT_PATH_DENY = [
    ".env", "**/.env", ".env.*", "**/*.pem", "**/*.key", "**/id_rsa*", "**/id_ed25519*",
    ".git/**", ".agent/**",
]
DEFAULT_COMMAND_DENY = [
    "sudo *", "su *", "*rm -rf /*", "*rm -rf ~*", "*rm -rf /", "*mkfs*", "*dd if=*",
    "*:(){*", "*> /dev/sd*", "*curl *|*sh*", "*wget *|*sh*", "*chmod -R 777 /*",
    "*shutdown*", "*reboot*", "*git push*--force*",
]


@dataclass
class Decision:
    mode: str
    reason: str


@dataclass
class Permissions:
    defaults: dict[str, str] = field(default_factory=lambda: dict(SAFE_DEFAULTS))
    tools: dict[str, str] = field(default_factory=dict)
    path_allow: list[str] = field(default_factory=list)
    path_deny: list[str] = field(default_factory=lambda: list(DEFAULT_PATH_DENY))
    command_allow: list[str] = field(default_factory=list)
    command_deny: list[str] = field(default_factory=lambda: list(DEFAULT_COMMAND_DENY))
    domain_allow: list[str] = field(default_factory=list)
    domain_deny: list[str] = field(default_factory=list)
    yolo: bool = False
    source: str = "built-in safe defaults"

    # ---------- loading ----------
    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, yolo: bool = False, source: str = "dict") -> "Permissions":
        data = data or {}
        p = cls(yolo=yolo, source=source)
        for cat, mode in (data.get("defaults") or {}).items():
            _check(cat in CATEGORIES, f"unknown category {cat!r}")
            _check(mode in MODES, f"invalid mode {mode!r} for category {cat}")
            p.defaults[cat] = mode
        for tool, mode in (data.get("tools") or {}).items():
            _check(mode in MODES, f"invalid mode {mode!r} for tool {tool}")
            p.tools[tool] = mode
        paths = data.get("paths") or {}
        cmds = data.get("commands") or {}
        doms = data.get("domains") or {}
        if "allow" in paths:
            p.path_allow = list(paths.get("allow") or [])
        if "deny" in paths:
            p.path_deny = list(paths.get("deny") or [])
        if "allow" in cmds:
            p.command_allow = list(cmds.get("allow") or [])
        if "deny" in cmds:
            p.command_deny = list(cmds.get("deny") or [])
        p.domain_allow = list(doms.get("allow") or [])
        p.domain_deny = list(doms.get("deny") or [])
        return p

    @classmethod
    def load(cls, path: str | os.PathLike | None, yolo: bool = False) -> "Permissions":
        if path is None:
            return cls(yolo=yolo)
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"permissions file not found: {path}")
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            data = json.loads(text)
        else:
            try:
                import yaml  # type: ignore

                data = yaml.safe_load(text)
            except ImportError:
                from . import miniyaml

                data = miniyaml.loads(text)
        return cls.from_dict(data, yolo=yolo, source=str(path))

    # ---------- decisions ----------
    def decide(self, tool: str, category: str, subject_kind: str | None = None,
               subject: str | None = None) -> Decision:
        _check(category in CATEGORIES, f"unknown category {category!r}")
        if tool in self.tools:
            mode, why = self.tools[tool], f"tool rule '{tool}: {self.tools[tool]}'"
        else:
            mode, why = self.defaults[category], f"category default '{category}: {self.defaults[category]}'"

        if subject is not None and subject_kind == "path":
            hit = _match_path(subject, self.path_deny)
            if hit:
                return Decision("deny", f"path '{subject}' matches deny pattern '{hit}'")
            if self.path_allow and not _match_path(subject, self.path_allow):
                return Decision("deny", f"path '{subject}' not in paths.allow")
        elif subject is not None and subject_kind == "command":
            cmd = " ".join(subject.split())
            hit = _first(cmd, self.command_deny)
            if hit:
                return Decision("deny", f"command matches deny pattern '{hit}'")
            hit = _first(cmd, self.command_allow)
            if hit and mode == "ask":
                return Decision("allow", f"command matches allow pattern '{hit}'")
        elif subject is not None and subject_kind == "url":
            host = (urlparse(subject).hostname or "").lower()
            if _match_domain(host, self.domain_deny):
                return Decision("deny", f"domain '{host}' is in domains.deny")
            if _match_domain(host, self.domain_allow) and mode == "ask":
                return Decision("allow", f"domain '{host}' is in domains.allow")

        if mode == "ask" and self.yolo:
            if category in YOLO_PROTECTED:
                return Decision("ask", f"{why}; --yolo ignored for '{category}' (set it to allow in the file yourself)")
            return Decision("allow", f"{why}; upgraded by --yolo")
        return Decision(mode, why)

    def summary(self) -> str:
        lines = [f"permissions: {self.source}" + ("  [--yolo]" if self.yolo else "")]
        lines += [f"  {c:8s} {self.defaults[c]}" for c in CATEGORIES]
        for t, m in sorted(self.tools.items()):
            lines.append(f"  tool {t}: {m}")
        return "\n".join(lines)


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError("permissions: " + msg)


def _first(text: str, patterns: list[str]) -> str | None:
    for pat in patterns:
        if fnmatch.fnmatchcase(text, pat):
            return pat
    return None


def _match_path(rel: str, patterns: list[str]) -> str | None:
    rel = rel.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    name = rel.rsplit("/", 1)[-1]
    for pat in patterns:
        cands = [pat]
        if pat.startswith("**/"):
            cands.append(pat[3:])
        if pat.endswith("/**"):
            cands.append(pat[:-3])
        for c in cands:
            if fnmatch.fnmatchcase(rel, c) or ("/" not in c and fnmatch.fnmatchcase(name, c)):
                return pat
    return None


def _match_domain(host: str, patterns: list[str]) -> bool:
    for pat in patterns:
        pat = pat.lower().lstrip(".")
        if host == pat or host.endswith("." + pat) or fnmatch.fnmatchcase(host, pat):
            return True
    return False
